import json
import lzma
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'py'))
import graphics

PRESETS = [
    ('enhanced', {
        'LOD_SWITCH': 2.0,
        'DRAW_NEAR': 2.0,
        'DRAW_FAR': 1.5,
        'PLACEMENT': 1.5,
        'TERRAIN_LOD': 1.5,
        'TERRAIN_TABLE': 1.5,
        'TILE_HIGH_STEP': 2,
        'TILE_MEDIUM_STEP': 2,
        'INSTANCING': 1.5,
        'SUN_NEAR_SHADOWMAP': 2048,
        'SUN_VOLUME_SAMPLES': 0,
        'LIGHT_SHADOW_DIST': 1.5,
        'LIGHT_FADE': 1.25,
        'LIGHT_FILTER': {},
        'LIGHT_VOLUME': {},
        'OCEAN': 1.5,
        'IMPACT': 1.5,
    }),
    ('ultra', {}),
    ('extreme', {
        'TERRAIN_LOD': 4.0,
        'SWITCH_TO_MESH': 4.0,
        'TERRAIN_SHADING_LAYERS': {(0, 0, 0, 1, 2, 3, 3, 4, 5, 6, 6, 7, 8): (0, 0, 0, 1, 1, 1, 2, 3, 4, 5, 6, 7, 8)},
        'TILE_HIGH_STEP': 4,
        'TILE_MEDIUM_STEP': 6,
    }),
]

DEFAULTS = {k: getattr(graphics, k) for k in set().union(*(p for _, p in PRESETS))}

FIT_FALLBACK = {
    'enhanced': ('ultra', {'13828:0', '13828:1', '15702:0', '15702:1', '15743:0', '15743:1',
                           '29186:0', '29186:1', '6670:0', '6670:1'}),
}


def build(scan, overrides):
    for k, v in DEFAULTS.items():
        setattr(graphics, k, v)
    for k, v in overrides.items():
        setattr(graphics, k, v)
    b = graphics.Builder()
    graphics.lod_meshes(b, scan)
    graphics.render(b, scan)
    graphics.lights(b, scan)
    graphics.impacts(b, scan)
    seen = set()
    for p in b.patches:
        key = (p['file'], p['pos'])
        if key in seen:
            sys.exit(f'overlapping patch at {key}: {p["note"]}')
        seen.add(key)
    return b


def pack(patches):
    files = {}
    for p in sorted(patches, key=lambda p: (p['file'], p['pos'])):
        files.setdefault(p['file'], []).append([p['pos'], p['old'], p['new']])
    data = json.dumps({'format': 1, 'count': len(patches), 'files': files}, separators=(',', ':'))
    return lzma.compress(data.encode('utf-8'), preset=9)


def main():
    scan = sys.argv[1]
    os.makedirs(os.path.join(HERE, 'build'), exist_ok=True)
    os.makedirs(os.path.join(HERE, 'app', 'presets'), exist_ok=True)
    built = {name: build(scan, overrides) for name, overrides in PRESETS}
    for name, _ in PRESETS:
        b = built[name]
        patches = b.patches
        if name in FIT_FALLBACK:
            source, objects = FIT_FALLBACK[name]
            obj = lambda p: p['note'].split(' ', 1)[0]
            swapped = [p for p in built[source].patches if obj(p) in objects]
            if {obj(p) for p in swapped} != objects:
                sys.exit(f'{name}: fit fallback objects missing from {source}')
            patches = [p for p in patches if obj(p) not in objects] + swapped
            print(f'{name}: {len(swapped)} values of {len(objects)} objects taken from {source} so their chunks fit')
        with open(os.path.join(HERE, 'build', f'patches_{name}.json'), 'w', encoding='utf-8') as f:
            json.dump(patches, f, indent=0)
        blob = pack(patches)
        with open(os.path.join(HERE, 'app', 'presets', f'{name}.vxp'), 'wb') as f:
            f.write(blob)
        counts = ', '.join(f'{k} {n}' for k, n in sorted(b.counts.items()))
        print(f'{name}: {len(patches)} patches in {len({p["file"] for p in patches})} files, '
              f'pack {len(blob) / 1e6:.1f} MB\n  {counts}')


if __name__ == '__main__':
    main()
