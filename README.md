# blitzBUS DOS 6.22 / 386 audit + clean interactive console

**This package does not modify C source, DOS image files or installed checksum manifests.** It generates a new PowerShell runner in `scripts/` and preserves the original one. It also includes a read-only log analyzer and a development roadmap.

## Install the host-only clean DOS console

Copy `bb_make_dos622_clean_console.py` and `bb_dos622_screen_host.ps1` into `C:\blitzBUS` (same directory). Run:

```powershell
cd C:\blitzBUS
python .\bb_make_dos622_clean_console.py selftest
python .\bb_make_dos622_clean_console.py probe
python .\bb_make_dos622_clean_console.py apply
python .\bb_make_dos622_clean_console.py verify
```

The original `scripts\bb_live_run.ps1` remains untouched. A new `scripts\bb_live_run_dos622.ps1` is generated, plus `scripts\bb_dos622_screen_host.ps1` and a SHA state file. If the original source has changed too much, `probe` refuses to proceed rather than guessing.

Use your existing environment settings (`BB_CPU=286`, `BB_SD_BOOT=1`, etc.) and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run_dos622.ps1 `
    -MicroDOS C:\microDOS `
    -Blitz86 C:\blitz86_v2 `
    -Port COM5 `
    -Seconds 180 `
    -ConsoleView Screen
```

`-ConsoleView Screen` redraws the 25 guest DOS text rows in-place; `Events` suppresses the screen and shows key diagnostics; `Raw` retains the unfiltered original output. Serial keyboard input and Ctrl+X exit remain owned by the existing runner. **The original raw CDC transcript is still written to `logs\bb-live-*-console.txt` in all modes.** Build and flash progress still displays normally before guest-screen takeover. This changes display, not the firmware's volume of USB printf traffic; fixing firmware log-level gating is recommended next.

If your PowerShell console does not support cursor-positioning, the tool will report a fallback warning. Use a regular Windows 10 PowerShell console with at least 80 columns; 100×30 is preferable. Running inside an IDE's redirected terminal may prevent `[Console]::KeyAvailable`, just as it does with the original runner.

Rollback **only the generated files**:

```powershell
python .\bb_make_dos622_clean_console.py restore
```

## Offline audit of logs / readable last DOS screen

```powershell
python .\bb_dos622_log_audit.py .\logs\bb-live-YYYYMMDD-HHMMSS-console.txt `
    --screen-output .\logs\last_dos_screen.txt `
    --json-output .\logs\last_dos_audit.json
```

The analyzer reads the raw transcript, reconstructs the last observed 25 text rows, and lists significant failures and noisy tag counts. It never edits the input log. Existing sample output is included for the latest submitted log.

Read `DOS622_386_CAPABILITY_AUDIT_2026-10-14.md` for verified support, the next missing EGA BIOS query, minimum Descent requirements and the subsystem milestone plan.

## Validation status

The Python installer passed temporary LF and CRLF source round-trips, raw-transcript preservation checks, SHA-verified generated-file checks, and exact restore checks. The log auditor was run successfully on the latest user-supplied full transcript. **PowerShell live serial rendering has not yet been tested on the physical Pico/Windows console.** The original runner is always available for fallback.
