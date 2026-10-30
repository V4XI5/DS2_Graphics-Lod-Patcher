import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, 'app')
BUILD = os.path.join(HERE, 'build')
DIST = os.path.join(HERE, 'dist')
NAME = 'VAXIS_DS2_Patcher'

sys.path.insert(0, APP)
import vaxis_core

VERSION = vaxis_core.VERSION
NUMS = tuple(int(x) for x in VERSION.split('.')) + (0,)

VERSION_INFO = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={NUMS}, prodvers={NUMS}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'VAXIS'),
      StringStruct('FileDescription', 'VAXIS Death Stranding 2 Graphics & LOD Patcher'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', '{NAME}'),
      StringStruct('LegalCopyright', 'VAXIS'),
      StringStruct('OriginalFilename', '{NAME}.exe'),
      StringStruct('ProductName', 'VAXIS DS2 Patcher'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    for p in vaxis_core.PRESETS:
        if not os.path.exists(os.path.join(APP, 'presets', p['id'] + '.vxp')):
            sys.exit(f'missing preset {p["id"]}; run build_presets.py first')
    os.makedirs(BUILD, exist_ok=True)
    version_file = os.path.join(BUILD, 'version_info.txt')
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(VERSION_INFO)
    icon = os.path.join(APP, 'vaxis.ico')
    sep = os.pathsep
    subprocess.check_call([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
        '--name', NAME, '--icon', icon, '--version-file', version_file,
        '--add-data', f'{os.path.join(APP, "presets")}{sep}presets',
        '--add-data', f'{icon}{sep}.',
        '--exclude-module', 'PIL', '--exclude-module', 'numpy',
        '--distpath', os.path.join(BUILD, 'pyi_dist'), '--workpath', os.path.join(BUILD, 'pyi_work'),
        '--specpath', BUILD, os.path.join(APP, 'VAXIS.py')])

    release = os.path.join(DIST, f'{NAME}_v{VERSION}')
    shutil.rmtree(release, ignore_errors=True)
    os.makedirs(release)
    shutil.copy2(os.path.join(BUILD, 'pyi_dist', NAME + '.exe'), release)
    with open(os.path.join(HERE, 'README.txt'), encoding='utf-8') as f:
        readme = f.read().replace('{version}', VERSION)
    with open(os.path.join(release, 'README.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(readme)
    archive = release + '.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in sorted(os.listdir(release)):
            z.write(os.path.join(release, n), f'{NAME}_v{VERSION}/{n}')
    size = os.path.getsize(os.path.join(release, NAME + '.exe'))
    print(f'release: {release} (exe {size / 1e6:.1f} MB)\nzip: {archive}')


if __name__ == '__main__':
    main()
