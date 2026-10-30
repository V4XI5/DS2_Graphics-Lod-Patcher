import bisect
import hashlib
import json
import lzma
import os
import re
import shutil
import struct
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import lz4.block

APP = 'VAXIS'
VERSION = '1.0.0'
GAME_FOLDER = 'DEATH STRANDING 2 - ON THE BEACH'
GAME_EXE = 'DS2.exe'
BACKUP_DIR = 'VAXIS_backup'
STATE_FILE = 'state.json'

PRESETS = [
    {
        'id': 'enhanced',
        'name': 'Enhanced',
        'tag': 'LIGHT',
        'intro': None,
        'bullets': [
            '2x model detail distance',
            '1.5-2x object draw distance',
            '1.5x vegetation and rocks',
            '1.5x terrain detail',
            '+2 high, +2 mid detail tiles',
            '3 sun shadow cascades',
            '1.5x light shadow distance',
            '1.5x ocean wave detail',
        ],
    },
    {
        'id': 'ultra',
        'name': 'Ultra',
        'tag': 'RECOMMENDED',
        'intro': None,
        'bullets': [
            '4x model detail distance',
            '2-3x object draw distance',
            '2x vegetation and rocks',
            '2x terrain detail',
            '+2 high, +4 mid detail tiles',
            '3 cascades, 4096 shadow map',
            '2x light shadows, sharper',
            '2x ocean wave detail',
        ],
    },
    {
        'id': 'extreme',
        'name': 'Extreme',
        'tag': 'HIGHEST',
        'intro': 'Everything in Ultra, plus:',
        'bullets': [
            '4x terrain detail',
            '4x terrain mesh range',
            '3x ground material distance',
            '+4 high, +6 mid detail tiles',
            'Best with 16 GB of VRAM',
        ],
    },
]

HEADER = struct.Struct('<IHHIIQQ')
ROW = struct.Struct('<QQIIB7s')
MAGIC = 0x52415344
LZ4 = 3
BATCH = 64
SPACE_MARGIN = 256 * 1024 * 1024


class PatchError(Exception):
    pass


def resource_path(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def preset(pid):
    for p in PRESETS:
        if p['id'] == pid:
            return p
    raise PatchError(f'Unknown preset "{pid}".')


def is_game_dir(path):
    return bool(path) and os.path.isfile(os.path.join(path, GAME_EXE)) and \
        os.path.isdir(os.path.join(path, 'LocalCacheWinGame', 'package'))


def steam_libraries():
    roots = []
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg:
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                 (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
                                 (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(os.path.normpath(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                pass
    libs = []
    for root in roots:
        libs.append(root)
        try:
            with open(os.path.join(root, 'steamapps', 'libraryfolders.vdf'), encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            libs.append(os.path.normpath(m.group(1).replace('\\\\', '\\')))
    seen, out = set(), []
    for lib in libs:
        if lib.lower() not in seen:
            seen.add(lib.lower())
            out.append(lib)
    return out


def find_game():
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    candidates = [here, os.path.dirname(here)]
    candidates += [os.path.join(lib, 'steamapps', 'common', GAME_FOLDER) for lib in steam_libraries()]
    for c in candidates:
        if is_game_dir(c):
            return os.path.realpath(c)
    return None


def game_running():
    try:
        out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {GAME_EXE}', '/NH', '/FO', 'CSV'],
                             capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise PatchError(f'Could not check whether the game is running ({e}).')
    return f'"{GAME_EXE.lower()}"' in out.lower()


def require_closed():
    if game_running():
        raise PatchError('Death Stranding 2 is running. Close the game completely, then try again.')


def resolve(game, name):
    device, rel = name.split(':', 1)
    if device == 'cache':
        return os.path.join(game, 'LocalCacheWinGame', rel.replace('/', os.sep))
    if device == 'game':
        return os.path.join(game, rel.replace('/', os.sep))
    raise PatchError(f'Unexpected file reference {name}.')


def read_table(path, name):
    try:
        with open(path, 'rb') as f:
            head = f.read(HEADER.size)
            if len(head) != HEADER.size:
                raise PatchError(f'{name} is not a valid game archive.')
            magic, _, _, count, _, _, _ = HEADER.unpack(head)
            if magic != MAGIC:
                raise PatchError(f'{name} is not a valid game archive.')
            table = f.read(count * ROW.size)
    except FileNotFoundError:
        raise PatchError(f'Game file missing: {name}. Verify the game files in Steam, then try again.')
    if len(table) != count * ROW.size:
        raise PatchError(f'{name} is truncated. Verify the game files in Steam, then try again.')
    return [ROW.unpack_from(table, i * ROW.size) for i in range(count)]


def chunk_writes(rows, patches, name):
    starts = [r[0] for r in rows]
    out = defaultdict(list)
    end = -1
    for pos, old_hex, new_hex in sorted(patches):
        old, new = bytes.fromhex(old_hex), bytes.fromhex(new_hex)
        if len(old) != len(new) or pos < end:
            raise PatchError(f'Preset data for {name} is damaged. Download the patcher again.')
        end = pos + len(new)
        off = pos
        while off < end:
            i = bisect.bisect_right(starts, off) - 1
            if i < 0 or not rows[i][0] <= off < rows[i][0] + rows[i][2]:
                raise PatchError(f'{name} does not match the game version this patcher was made for.')
            stop = min(end, rows[i][0] + rows[i][2])
            out[i].append((off, old[off - pos:stop - pos], new[off - pos:stop - pos]))
            off = stop
    return out


def read_range(game, name, pos, size):
    path = resolve(game, name)
    rows = read_table(path, name)
    i = bisect.bisect_right([r[0] for r in rows], pos) - 1
    out = bytearray()
    with open(path, 'rb') as f:
        while len(out) < size:
            if i < 0 or i >= len(rows) or not rows[i][0] <= pos + len(out) < rows[i][0] + rows[i][2]:
                raise PatchError(f'{name} does not match the game version this patcher was made for.')
            base, coff, usize, csize, ctype, _ = rows[i]
            if ctype != LZ4:
                raise PatchError(f'{name} uses an unsupported compression type.')
            f.seek(coff)
            try:
                data = lz4.block.decompress(f.read(csize), uncompressed_size=usize)
            except lz4.block.LZ4BlockError:
                raise PatchError(f'{name} contains damaged data.')
            start = pos + len(out) - base
            out += data[start:start + size - len(out)]
            i += 1
    return bytes(out)


def patch_chunk(row, raw, writes, name):
    base, _, size, _, ctype, _ = row
    if ctype != LZ4:
        raise PatchError(f'{name} uses an unsupported compression type.')
    try:
        buf = bytearray(lz4.block.decompress(raw, uncompressed_size=size))
    except lz4.block.LZ4BlockError:
        raise PatchError(f'{name} contains damaged data. Verify the game files in Steam, then try again.')
    for off, old, _ in writes:
        if buf[off - base:off - base + len(old)] != old:
            raise PatchError(
                f'{name} does not contain the expected original values. The game was updated since this '
                f'patcher version was made, or another mod changed this file. Remove other mods (or use '
                f'"Verify integrity of game files" in Steam), then try again.')
    for off, _, new in writes:
        buf[off - base:off - base + len(new)] = new
    data = bytes(buf)
    packed = lz4.block.compress(data, mode='high_compression', compression=12, store_size=False)
    if lz4.block.decompress(packed, uncompressed_size=size) != data:
        raise PatchError(f'{name}: compression check failed. Nothing was changed.')
    if len(packed) > len(raw):
        raise PatchError(f'{name}: a patched block does not fit its original space. Nothing was changed.')
    return len(packed), packed + bytes(len(raw) - len(packed))


def backup_dir(game):
    return os.path.join(game, BACKUP_DIR)


def read_state(game):
    path = os.path.join(backup_dir(game), STATE_FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            state = json.load(f)
    except (OSError, ValueError):
        raise PatchError(f'The backup record {path} is damaged. Verify the game files in Steam to get the '
                         f'original files back.')
    if state.get('app') != APP:
        raise PatchError(f'{path} was not written by this patcher.')
    return state


def write_state(game, state):
    path = os.path.join(backup_dir(game), STATE_FILE)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(state, f, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(path + '.tmp', path)


BLOB = re.compile(r'^\d{2}_[A-Za-z0-9._-]+\.(orig|new)$')


def remove_backup(game):
    d = backup_dir(game)
    try:
        names = os.listdir(d)
    except FileNotFoundError:
        return
    for n in names:
        if n in (STATE_FILE, STATE_FILE + '.tmp') or BLOB.match(n):
            try:
                os.remove(os.path.join(d, n))
            except FileNotFoundError:
                pass
    try:
        os.rmdir(d)
    except OSError:
        pass


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def classify(f, e):
    f.seek(e['coff'])
    slot = sha1(f.read(e['csize']))
    f.seek(HEADER.size + e['chunk'] * ROW.size)
    row = f.read(ROW.size).hex()
    slot_state = 'orig' if slot == e['sha1'] else 'new' if slot == e['new_sha1'] else None
    row_match = {'orig': row == e['row'], 'new': row == e['new_row']}
    if slot_state and row_match[slot_state]:
        return slot_state, slot_state
    row_state = 'orig' if row_match['orig'] else 'new' if row_match['new'] else None
    return slot_state, row_state


def status(game):
    state = read_state(game)
    if not state or state['status'] == 'preparing':
        return 'none', None, 'No VAXIS preset is installed.'
    name = preset(state['preset'])['name']
    seen = set()
    for fe in state['files']:
        path = resolve(game, fe['name'])
        if not os.path.exists(path) or os.path.getsize(path) != fe['size'] or not fe['entries']:
            seen.add('changed')
            continue
        with open(path, 'rb') as f:
            seen.update(s for s in classify(f, fe['entries'][0]))
    if state['status'] == 'installed' and seen == {'new'}:
        return 'installed', state['preset'], f'{name} is installed.'
    if seen <= {'orig'}:
        return 'reverted', state['preset'], (f'{name} was removed by a game update or file check. '
                                             f'Install a preset again, or Uninstall to clear the backup.')
    return 'partial', state['preset'], (f'{name} is only partly installed (the last run was interrupted '
                                        f'or the game was updated). Click Uninstall to restore the originals.')


class Progress:
    def __init__(self, report, total):
        self.report, self.total, self.done = report, max(1, total), 0

    def step(self, n, text):
        self.done += n
        self.report(min(1.0, self.done / self.total), text)


def load_preset(pid):
    preset(pid)
    path = resource_path(os.path.join('presets', pid + '.vxp'))
    try:
        with open(path, 'rb') as f:
            data = json.loads(lzma.decompress(f.read()))
    except (OSError, lzma.LZMAError, ValueError):
        raise PatchError(f'Preset data {path} is missing or damaged. Download the patcher again.')
    if data.get('format') != 1:
        raise PatchError('Preset data is from a different patcher version.')
    return data['files']


def install(game, pid, log=print, report=lambda f, t: None):
    if not is_game_dir(game):
        raise PatchError('That folder does not contain Death Stranding 2 (DS2.exe and LocalCacheWinGame).')
    require_closed()
    name = preset(pid)['name']

    state = read_state(game)
    if state and state['status'] != 'preparing':
        code, current, _ = status(game)
        if code == 'installed' and current == pid:
            log(f'{name} is already installed.')
            report(1.0, f'{name} is already installed')
            return
        log('Removing the current preset first, so presets never stack.')
        uninstall(game, log, report)
    elif state:
        remove_backup(game)

    files = load_preset(pid)
    log(f'Loaded {name}: {sum(len(v) for v in files.values())} values in {len(files)} game files.')

    plan, slots = [], 0
    for fname in sorted(files):
        path = resolve(game, fname)
        rows = read_table(path, fname)
        writes = chunk_writes(rows, files[fname], fname)
        slots += sum(rows[i][3] for i in writes)
        plan.append((fname, path, rows, writes))
        try:
            open(path, 'r+b').close()
        except PermissionError:
            raise PatchError(f'Windows denied write access to {fname}. Make sure the game is closed, or run '
                             f'the patcher as administrator.')
    free = shutil.disk_usage(game).free
    need = 2 * slots + SPACE_MARGIN
    if free < need:
        raise PatchError(f'Not enough free disk space on the game drive: {need / 2**30:.1f} GB needed, '
                         f'{free / 2**30:.1f} GB free.')

    chunks = sum(len(w) for _, _, _, w in plan)
    progress = Progress(report, 2 * chunks)
    os.makedirs(backup_dir(game), exist_ok=True)
    state = {'app': APP, 'version': VERSION, 'preset': pid, 'status': 'preparing', 'files': []}
    write_state(game, state)

    log(f'Preparing {chunks} data blocks (the game files are not changed yet)...')
    try:
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
            for idx, (fname, path, rows, writes) in enumerate(plan):
                safe = f'{idx:02d}_' + re.sub(r'[^A-Za-z0-9._-]', '_', fname.split(':', 1)[1])
                fe = {'name': fname, 'size': os.path.getsize(path), 'orig': safe + '.orig',
                      'new': safe + '.new', 'entries': []}
                state['files'].append(fe)
                order = sorted(writes)
                with open(path, 'rb') as f, \
                        open(os.path.join(backup_dir(game), fe['orig']), 'wb') as bo, \
                        open(os.path.join(backup_dir(game), fe['new']), 'wb') as bn:
                    for s in range(0, len(order), BATCH):
                        batch = order[s:s + BATCH]
                        raws = []
                        for i in batch:
                            f.seek(rows[i][1])
                            raws.append(f.read(rows[i][3]))
                        news = list(pool.map(lambda a: patch_chunk(*a),
                                             [(rows[i], raw, writes[i], fname) for i, raw in zip(batch, raws)]))
                        for i, raw, (packed, new) in zip(batch, raws, news):
                            row = list(rows[i])
                            row[3] = packed
                            fe['entries'].append({'chunk': i, 'coff': rows[i][1], 'csize': len(raw), 'at': bo.tell(),
                                                  'row': ROW.pack(*rows[i]).hex(), 'new_row': ROW.pack(*row).hex(),
                                                  'sha1': sha1(raw), 'new_sha1': sha1(new)})
                            bo.write(raw)
                            bn.write(new)
                        progress.step(len(batch), f'Preparing {fname.split(":", 1)[1]}')
                    bo.flush()
                    os.fsync(bo.fileno())
        write_state(game, state)
        require_closed()
    except BaseException:
        remove_backup(game)
        raise

    state['status'] = 'installing'
    write_state(game, state)
    log('Writing the patched data into the game files...')
    try:
        for fe in state['files']:
            path = resolve(game, fe['name'])
            with open(path, 'r+b') as f, open(os.path.join(backup_dir(game), fe['new']), 'rb') as bn:
                for e in fe['entries']:
                    bn.seek(e['at'])
                    f.seek(e['coff'])
                    f.write(bn.read(e['csize']))
                    f.seek(HEADER.size + e['chunk'] * ROW.size)
                    f.write(bytes.fromhex(e['new_row']))
                f.flush()
                os.fsync(f.fileno())
                for e in fe['entries']:
                    if classify(f, e) != ('new', 'new'):
                        raise PatchError(f'{fe["name"]}: the written data did not verify.')
            progress.step(len(fe['entries']), f'Writing {fe["name"].split(":", 1)[1]}')
    except BaseException as e:
        log(f'Writing failed ({e}). Restoring the original files...')
        try:
            uninstall(game, log, report)
        except Exception as e2:
            log(f'Automatic restore failed too ({e2}). Run Uninstall again, or verify the game files in Steam.')
        raise

    state['status'] = 'installed'
    write_state(game, state)
    for fe in state['files']:
        try:
            os.remove(os.path.join(backup_dir(game), fe['new']))
        except OSError:
            pass
    log(f'{name} installed: {chunks} data blocks patched. The original data is backed up in {BACKUP_DIR}.')
    report(1.0, f'{name} installed')


def uninstall(game, log=print, report=lambda f, t: None):
    require_closed()
    state = read_state(game)
    if not state:
        log('Nothing to uninstall. No VAXIS preset is installed.')
        report(1.0, 'Nothing to uninstall')
        return
    if state['status'] == 'preparing':
        remove_backup(game)
        log('Removed an unfinished backup. The game files were not changed.')
        report(1.0, 'Nothing was installed')
        return

    progress = Progress(report, sum(len(fe['entries']) for fe in state['files']))
    changed, restored = [], 0
    for fe in state['files']:
        path = resolve(game, fe['name'])
        if not os.path.exists(path) or os.path.getsize(path) != fe['size']:
            changed.append(fe['name'])
            progress.step(len(fe['entries']), 'Checking')
            continue
        with open(path, 'r+b') as f:
            states = [classify(f, e) for e in fe['entries']]
            if any(None in s for s in states):
                changed.append(fe['name'])
                progress.step(len(fe['entries']), 'Checking')
                continue
            todo = [e for e, s in zip(fe['entries'], states) if s != ('orig', 'orig')]
            if todo:
                with open(os.path.join(backup_dir(game), fe['orig']), 'rb') as bo:
                    for e in todo:
                        bo.seek(e['at'])
                        raw = bo.read(e['csize'])
                        if sha1(raw) != e['sha1']:
                            raise PatchError(f'The backup of {fe["name"]} is damaged. Verify the game files in '
                                             f'Steam to get the original files back.')
                        f.seek(e['coff'])
                        f.write(raw)
                        f.seek(HEADER.size + e['chunk'] * ROW.size)
                        f.write(bytes.fromhex(e['row']))
                f.flush()
                os.fsync(f.fileno())
                for e in todo:
                    if classify(f, e) != ('orig', 'orig'):
                        raise PatchError(f'{fe["name"]}: restoring did not verify. Verify the game files in Steam.')
                restored += 1
        progress.step(len(fe['entries']), f'Restoring {fe["name"].split(":", 1)[1]}')

    remove_backup(game)
    if changed:
        log(f'{len(changed)} game files changed since they were patched (game update or file check) and were '
            f'left as they are. If the game misbehaves, use "Verify integrity of game files" in Steam.')
    log(f'Uninstalled: restored {restored} game files to their original data.')
    report(1.0, 'Original game files restored')


USAGE = 'Usage: python vaxis_core.py <game dir> status|install <preset>|uninstall'


def main():
    if len(sys.argv) < 3 or (sys.argv[2] == 'install' and len(sys.argv) < 4):
        sys.exit(USAGE)
    game, cmd = sys.argv[1], sys.argv[2]
    try:
        if cmd == 'status':
            print(status(game))
        elif cmd == 'install':
            install(game, sys.argv[3], report=lambda f, t: None)
        elif cmd == 'uninstall':
            uninstall(game)
        else:
            sys.exit(USAGE)
    except PatchError as e:
        sys.exit(f'error: {e}')


if __name__ == '__main__':
    main()
