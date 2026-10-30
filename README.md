# VAXIS - Death Stranding 2 Graphics & LOD Patcher

Improves draw distance, level of detail (LOD), terrain, shadows and lighting in
Death Stranding 2: On the Beach. Graphics and LOD.



## INSTALL

  1. Close the game completely.
  2. Run VAXIS_DS2_Patcher.exe. It finds a Steam install automatically. If it does not,
     click Browse and select the folder that contains DS2.exe.
  3. Pick a preset and click Install. This takes one to two minutes.

  To switch presets, install another one. The patcher restores the original data first,
  so presets never stack.


## PRESETS

  01 Enhanced (light)
     - 2x model detail distance
     - 1.5-2x object draw distance
     - 1.5x vegetation and rocks
     - 1.5x terrain detail
     - +2 high, +2 mid detail tiles
     - 3 sun shadow cascades
     - 1.5x light shadow distance
     - 1.5x ocean wave detail

  02 Ultra (recommended)
     - 4x model detail distance
     - 2-3x object draw distance
     - 2x vegetation and rocks
     - 2x terrain detail
     - +2 high, +4 mid detail tiles
     - 3 cascades, 4096 shadow map
     - 2x light shadows, sharper
     - 2x tar wave movement.

  03 Extreme (highest) (may cause issues)
     Everything from preset 2, plus:
     - 4x terrain detail
     - 4x terrain mesh range
     - 3x ground material distance
     - +4 high, +6 mid detail tiles
     - Best with GPU's with 16 GB of VRAM


## How it works

Every preset is a list of same-size value edits inside the game's DSAR archives
(`LocalCacheWinGame/package`). Install runs in two phases:

1. Prepare: every chunk a preset touches is decompressed, each replaced value is checked against
   the expected original, the new values are applied, and the chunk is recompressed (LZ4HC) and
   must fit its original slot. Original chunks go to `VAXIS_backup` in the game folder, new ones
   to a staging file. The game files are not touched in this phase.
2. Write: the staged chunks and their chunk table rows are written and verified.

Uninstall writes the original chunks and rows back, only where the data is still exactly what
the patcher wrote or the original. Installing another preset uninstalls the current one first.


## Layout
Preset files (`.vxp`) are LZMA-compressed JSON:
`{"format": 1, "count": n, "files": {archive: [[offset, old_hex, new_hex], ...]}}`.


```
vaxis/
  app/
    VAXIS.py          GUI (tkinter)
    vaxis_core.py     install / uninstall / status, archive handling; also a command line
    game_fonts.py     loads the game's own fonts from the player's game files for the GUI
    presets/*.vxp     the three presets (prebuilt patch lists)
    vaxis.ico         window and exe icon
  build_presets.py    builds presets/*.vxp from the graphics builder and the game data scans
  build_exe.py        builds the one-file exe, the release README and the zip
  make_icon.py        draws vaxis.ico
  shot.py             runs a build in self-test mode and screenshots its window
  README.txt          release README (template; {version} is filled in by build_exe.py)
py/
  graphics.py         graphics and LOD value builder used by build_presets.py
requirements.txt
```

## Requirements

- Windows, Python 3.10 or newer (built with 3.14)
- `pip install -r requirements.txt`
  - `lz4`: required by the patcher
  - `pyinstaller`: building the exe
  - `pillow`: only for `make_icon.py` and `shot.py`

## Run from source

```
python vaxis/app/VAXIS.py
```

Command line (no GUI):

```
python vaxis/app/vaxis_core.py "<game folder>" status
python vaxis/app/vaxis_core.py "<game folder>" install enhanced|ultra|extreme
python vaxis/app/vaxis_core.py "<game folder>" uninstall
```

## Build the release

```
python vaxis/build_exe.py
```

Output: `vaxis/dist/VAXIS_DS2_Patcher_v<version>/` (exe and README.txt) and the matching `.zip`.
The version comes from `VERSION` in `vaxis_core.py`.


```
python vaxis/shot.py out.png selftest.txt "<full path to VAXIS_DS2_Patcher.exe>"
```


## Rebuilding the presets

The `.vxp` files are prebuilt. To regenerate them (for example after changing a preset in
`build_presets.py`):

```
python -I vaxis/build_presets.py <scan dir>
```

`<scan dir>` must contain the game data scans `lodmesh.jsonl`, `render.jsonl`, `render2.jsonl`,
`lights.jsonl` and `impacts.jsonl` (object dumps of the game's archives, about 140 MB, not
included). After changing a preset, check that every patched chunk still fits by installing it
on unmodified game files: the prepare phase refuses before writing anything if a chunk does not
fit. Enhanced takes Ultra's values for a few tiny LOD meshes for that reason (`FIT_FALLBACK`).

Keep `PLACEMENT` at 2.0 or lower: at 3x the game's procedural placement buffer overflows and
vegetation flickers in and out close to the camera.
