# blitzBUS DOS 6.22 — automatic two-window console V1

## Result

Run a single command. The existing PowerShell console keeps DOS keyboard
input and all COM5 access. A separate PowerShell window automatically opens
using the existing CP437 / 16-color DOS screen renderer, reading the same
raw capture **without opening COM5 or writing guest input**.

```
bb.bat dos boot
  |
  +-- THIS window: interactive DOS / disk-swap control / CLI events (COM5 OWNER)
  |
  +-- NEW window: DOS 80x25 CP437/VGA color display (RAW LOG FOLLOWER ONLY)
  |
  +-- C:\blitzBUS\logs\bb-live-YYYYMMDD-HHMMSS-console.txt (RAW, unchanged)
```

The new viewer uses `scripts/bb622_descent_color_host.ps1` without changing it.
The SHA-guarded `scripts/bb_live_run_dos622_irqtrial.ps1` is also unchanged.
The installer makes only a guarded edit to the unified CLI
`scripts/bb_cli.py`, adds two full script files, and backs up the original CLI.
It does not edit firmware, SD/floppy/HDD images, or IRQ0 state. Unlike a Git
patch, it checks exact source anchors and refuses incompatible local changes.

## Install

1. Extract `BLITZBUS_DOS_DUAL_CONSOLE_V1.zip` to `C:\blitzBUS`, so the installer
   is `C:\blitzBUS\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py`.
2. Execute from PowerShell:

```powershell
cd C:\blitzBUS
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py selftest
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py probe
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py apply
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py verify
.\bb.bat dos verify
```

The existing `bb.bat dos verify` must continue to pass the *original* DOS
lineage checks, because the SHA-protected runner is untouched.

## Run

For a no-build/no-flash session with automatic color window:

```powershell
.\bb.bat dos boot -NoBuild -NoFlash -Seconds 180
```

The primary window now defaults to the quieter `Events` mode. This prevents
`[bb622-cells] row=` raw hex lines from flooding the interactive terminal.
For full raw debug output in the primary window **as well as** the color screen:

```powershell
.\bb.bat dos boot -NoBuild -NoFlash -Seconds 180 -ConsoleView Raw
```

For a single-window/headless session:

```powershell
.\bb.bat dos boot -NoBuild -NoFlash -Seconds 180 -NoColorWindow
```

All existing PowerShell runner flags (`-AutoTests`, `-PhaseProfile`,
`-NoInput`, `-Port`, `-Seconds`, etc.) are still passed through unchanged.
As before, omitting `-NoBuild -NoFlash` allows the original runner to
build and flash. `bb.bat dos boot --dry-run` remains side-effect free.

Use the **original/main window** for DOS commands, Alt+G floppy controls,
Ctrl+] statistics, and Ctrl+X exit. The screen window is display-only;
Ctrl+X or Esc there closes just the viewer. The color window also closes
shortly after its DOS owner exits. One serial port has only one reader.

## Reopen an existing capture without COM5

To inspect a previous raw log in the same VGA renderer:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\bb622_color_follow.ps1 `
  -Log 'C:\blitzBUS\logs\bb-live-20261015-042625-console.txt' -Replay
```

This prints into the terminal where you run it. Open a separate PowerShell
window to use this standalone replay while another session is active.

## Rollback

```powershell
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py verify
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py restore
.\bb.bat dos verify
```

This restores `scripts/bb_cli.py` exactly from
`backups/bb_dos_dual_console_v1_state/cli.original` and removes only the two
new files added by this package. It will **refuse** rollback if you have
changed an installed file, rather than discarding unrelated edits.

## Test status

- Package installer: LF/CRLF/BOM exact-anchor test passed.
- Package installer: synthetic apply/verify/restore with SHA rollback passed.
- Actual Windows Terminal / COM5 dual-window run: **not yet tested**.
- Neither the real DOS IRQ0 one-shot nor automatic IRQ0 delivery is enabled
  by this package.
