VAXIS - Death Stranding 2 Graphics & LOD Patcher  v{version}
==========================================================

Improves draw distance, level of detail (LOD), terrain, shadows and lighting in
Death Stranding 2: On the Beach. Graphics and LOD only: gameplay, physics, effects and the
user interface are not changed.


PRESETS

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
     - 2x ocean wave detail

  03 Extreme (highest)
     Everything in Ultra, plus:
     - 4x terrain detail
     - 4x terrain mesh range
     - 3x ground material distance
     - +4 high, +6 mid detail tiles
     - Best with 16 GB of VRAM


INSTALL

  1. Close the game completely.
  2. Run VAXIS_DS2_Patcher.exe. It finds a Steam install automatically. If it does not,
     click Browse and select the folder that contains DS2.exe.
  3. Pick a preset and click Install. This takes one to two minutes.

  To switch presets, install another one. The patcher restores the original data first,
  so presets never stack.


UNINSTALL

  Run the patcher and click Uninstall. This restores the original data byte for byte and
  deletes the backup.

  Alternative: in Steam, right-click the game > Properties > Installed Files >
  Verify integrity of game files.


NOTES

  - Before anything is written, the patcher checks every value it changes against the
    original game data and checks that every patched block fits. If any check fails,
    nothing is changed.
  - The original data of every changed block is saved in VAXIS_backup inside the game
    folder (about 1 GB). Do not delete it while a preset is installed.
  - About 2.5 GB of free disk space is needed on the game drive during installation.
  - The patcher refuses to run while the game is running.
  - Game updates may replace patched files. Run the patcher again after an update. If an
    update changed the data this version patches, the patcher refuses to install and
    changes nothing until an updated version is available.
  - Other mods that change the same game files must be removed first. The patcher refuses
    to install over modified data.
  - Higher presets draw more detail and use more VRAM and GPU time.
  - The patcher window uses the game's own fonts. They are read from your game files when
    the patcher starts and are only used by the patcher window while it is open. No fonts
    are included in the download.
  - Windows SmartScreen or antivirus software may warn about an unsigned program. The
    patcher only edits the game's data archives in LocalCacheWinGame and writes its
    backup to VAXIS_backup.


Made by VAXIS.
