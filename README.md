# blitzBUS DOS 6.22 — swap console controls V1 + V2.2 Windows self-test

This is a **host-only correction** for an *already installed* `BB_DOS622_SWAP_LCD_V2` layer. It doesn't modify `src`, `sd_boot`, the pre-existing PowerShell runners, older state/repair manifests, or SD media. Don't restore/reinstall your working DOS 6.22 firmware.

## What happened

1. `bb_dos622_swap_lcd_v2_1.py selftest` fails at the final historic-SD-clockfix metadata test **on Windows only**. The test builds a key such as `.bb_dos622_sd_clockfix_v1_state\\repair.json`, but V2.1 compares it to a forward-slash string. The new `bb_dos622_swap_lcd_v2_2.py` normalizes separators for that one *known* schema. This doesn't change installed files or historical SHA-256 values. V2.2 `selftest` and `verify` are appropriate; `probe`/`apply` are **not** because V2 is already installed.
2. F9 can be intercepted by Windows consoles (and the original menu's feedback only appears in the title bar). The new **separate** runner accepts both F9 and Ctrl+G, and reads a disk-swap request file from `logs` so a second PowerShell window can direct A: or B: disk swaps even when the key never arrives.

## Copy into `C:\blitzBUS`

- `bb622_swap_controls_fix_v1.py`
- `bb_dos622_swap_lcd_v2_2.py`

Keep the installed V2.1 script, `bb_dos622_atbios_v1.py`, `bb_dos622_color_host.ps1`, all previous runners, all manifests, and all SD card files. **Do not overwrite them.**

## Verify old installed state

```powershell
cd C:\blitzBUS
python .\bb_dos622_swap_lcd_v2_2.py selftest
python .\bb_dos622_swap_lcd_v2_2.py verify
python .\bb_dos622_lineage_verify_v10.py verify
```

The old script is replaced **only as a CLI entry point** with V2.2 when you want to verify/test. V2.2 uses the original `.bb_dos622_swap_lcd_v2_state` directory and does not create another install layer.

## Generate the independent runner

```powershell
python .\bb622_swap_controls_fix_v1.py selftest
python .\bb622_swap_controls_fix_v1.py probe
python .\bb622_swap_controls_fix_v1.py apply
python .\bb622_swap_controls_fix_v1.py verify
```

That creates exactly two new files:

- `scripts\bb_live_run_dos622_controls.ps1`
- `scripts\bb622_request_disk.ps1`

It checks the original swap runner against the installed manifest before generating them. The source runner and installed checksum manifests do **not** change, and a separate exact-output checksum manifest is recorded in `.bb622_swap_controls_v1_state`.

## Run the new unlimited console

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\bb_live_run_dos622_controls.ps1 `
  -MicroDOS C:\microDOS `
  -Blitz86 C:\blitz86_v2 `
  -Port COM5 -Seconds 0 -ConsoleView Screen
```

`-Seconds 0` stays connected until Ctrl+X. This command retains the existing color/CP437 screen and logs everything in `logs\bb-live-*-console.txt`. It normally rebuilds/flashes as before. To **attach to an already running Pico without resetting it**, also pass `-NoBuild -NoFlash`, but note: the color console only receives *changes* to the guest screen, so it may show blank/partial rows until DOS updates the screen.

## Swap disks (two independent methods)

**Method 1 — in the main DOS console:** **Ctrl+G**, then **A**, then **2**. F9 continues to work if Windows delivers it. For Descent disk 3, use **Ctrl+G**, **B**, **3**. The number sends the command immediately. Wait for an `A:2 OK` / `B:3 OK` acknowledgement before pressing Enter inside the DOS installer.

**Method 2 — in a *second* PowerShell window** (does not open COM5 and is not affected by function-key interception):

```powershell
cd C:\blitzBUS
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb622_request_disk.ps1 -Drive A -Disk 2
```

For Descent disk 3:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb622_request_disk.ps1 -Drive B -Disk 3
```

The active DOS runner polls `logs\bb622-swap.request`, removes it, and forwards the same three-byte private request to the already-installed Pico firmware (`0x1C`, drive, number). Firmware confirms via `[bb622-swap] A:2 OK ...` or `FAIL ...` in the raw transcript. To monitor acknowledgements from the second window:

```powershell
Get-Content (Get-ChildItem .\logs\bb-live-*-console.txt | Sort-Object LastWriteTime | Select-Object -Last 1).FullName -Wait -Tail 20
```

**Never press Enter on the DOS disk prompt before `OK`.** `DOS6222.IMG` / `DESCENT3.IMG` must exist under `BLITZBUS\` on the microSD (each exactly 1,474,560 bytes). The existing A image is read-only and a failed swap retains the old image.

## Rollback

```powershell
python .\bb622_swap_controls_fix_v1.py verify
python .\bb622_swap_controls_fix_v1.py restore
```

This removes **only** the two new host scripts and their independent state directory; it does not modify the already working V2 layer, your DOS images, or any previous checksum record.

## Validation and limitations

- Host-only installer LF and CRLF self-tests passed, including original-runner SHA precondition and byte-exact rollback.
- V2.2 self-test passed on Linux with an explicit simulated Windows-backslash repair-path regression and LF/CRLF cascade tests. PowerShell cannot be executed in this Linux test runtime, so live Ctrl+G/F9 and file-swap commands still require a Windows + Pico session.
- This intentionally does *not* reflash, replace firmware, edit LCD driver, alter the 80x25 color display, or make C: bootable. It fixes the actual host control and misleading regression-test problems.
