# blitzBUS DOS 6.22 — KEYB AH=A2h compatibility fix (V1)

**Date:** 2026-10-14  
**Target:** `C:\blitzBUS\src\bb_live.c` (local file *after* `bb_dos622_keyb92_v1.py`).  
**Goal:** Allow genuine MS-DOS 6.22's `KEYB` initialization to pass the undocumented `INT 16h AH=A2h` 122-key keyboard capability check.

## Observed hardware blocker

```
[bb622-keyb92] KEYB INT16/AH=92 in-ax=9200 out-ax=8000 (IBM enhanced keyboard)
[bb622-missing-bios] unhandled INT 16 AX=A200 BX=01B5 CX=0001 DX=2402
    at=1016:1262; null IVT, stopping safely
```

`KEYB` uses AH=A2h to test support for 122-key keyboard services. An ordinary 101/102-key enhanced BIOS must **not** claim that support. The new handler returns `AX` unchanged (`A200h` for the captured call, i.e. `AH > 80h`), and leaves flags, instruction pointer, rewind, and all other registers alone. The existing AH=92h response remains intact. The handler is in shared `bb_v22_keyboard()`, reached by both interpreter and blitz86 native paths.

## Installation

1. Unzip `BLITZBUS_DOS622_KEYBA2_V1.zip` to a folder of your choice.
2. Copy the complete `bb_dos622_keyba2_v1.py` file to `C:\blitzBUS`.
3. In **PowerShell**, run:

```powershell
cd C:\blitzBUS
python .\bb_dos622_keyba2_v1.py selftest
python .\bb_dos622_keyba2_v1.py probe
python .\bb_dos622_keyba2_v1.py apply
python .\bb_dos622_keyba2_v1.py verify

# Optional: confirm earlier installers still verify.
python .\bb_dos622_keyb92_v1.py verify
python .\bb_dos622_irq0_isolation_v1.py verify
python .\bb_dos622_sram_floor_v1.py verify
python .\bb_dos622_textio_psram_v1.py verify
python .\bb_dos622_ipl_v1.py verify
```

The script **refuses to modify the repository** unless `src/bb_live.c` is exactly 90,997 bytes and its SHA-256 begins `99c40b35f00e`, matching the local file reported in the attached 2026-10-14 hardware handoff. It also refuses to modify the repository if the KEYB92 parent installer state or any previously tracked `src/bb_live.c` parent SHA is missing/mismatched. If it refuses, **don't bypass the safety checks**: supply the current local `src/bb_live.c` and relevant manifests.

The installer backs up each changed file, changes the shared handler once, updates **all** `.bb_dos622_*_state/manifest.json` parent manifests tracking `src/bb_live.c`, and verifies checksums. Backups are byte-exact; file replacement uses atomic same-directory renames. Neither the SD images nor the DOS2 boot path are modified.

## Hardware run — unchanged DOS6 debug configuration

```powershell
cd C:\blitzBUS

$env:BB_HOT_THRESHOLD = '32'
$env:BB_EVICT_CHUNK   = '4096'
$env:BB_EVICT_ROOM    = '2048'
$env:BB_BBUF          = '1'
$env:BB_CODE_KB       = '232'
$env:BB_CPU           = '286'
$env:BB_SD_BOOT       = '1'
$env:BB_LCD_PERI_HZ   = '150000000'
$env:BB_LCD_SPI_HZ    = '75000000'
$env:BB_LCD_LACE      = '1'

powershell -NoProfile -ExecutionPolicy Bypass -File `
    .\scripts\bb_live_run.ps1 `
    -MicroDOS C:\microDOS `
    -Blitz86 C:\blitz86_v2 `
    -Port COM5 `
    -Seconds 180
```

At the known `Starting MS-DOS...` input loop, press Enter once. Expected *new diagnostic* (not a claim of successful DOS6 boot):

```
[bb622-keyba2] KEYB INT16/AH=A2 unsupported 122-key; AX=A200 preserved
```

**Next acceptance:** No `unhandled INT 16 AX=A200`; execution advances further. Keep capturing the serial log to find the next real blocker. For a full boot, verify a genuine `A:\>` or `C:\>` prompt and run `VER`, `DIR`, and `MEM`. IRQ0 is **still intentionally suppressed for DOS6** by the existing diagnostic layer; it must be repaired and reenabled after the shell works. Don't begin 386/Descent debugging yet.

## Exact reversal

```powershell
cd C:\blitzBUS
python .\bb_dos622_keyba2_v1.py verify
python .\bb_dos622_keyba2_v1.py restore
python .\bb_dos622_keyb92_v1.py verify
```

`restore` rejects unrelated changes by default, and restores the original source and all parent manifest bytes, deleting only this installer's own state directory. An additional `recover` subcommand can undo a *partially interrupted install* only if each relevant file still matches one of the recorded original/installed SHA values. Use `recover` only for interrupted installation recovery, not for routine rollback.

## Testing scope and known limitations

- **Passed locally**: Python installer tests for LF/CRLF/mixed files, unique anchors/idempotency, parent manifest update, byte-exact restore; an independent C11 compile-and-run contract covering AX/FLAGS/IP/rewind preservation, the existing AH=92h branch in the simulated fixture, and DOS2 gating.
- **Not yet run here**: Compilation against the user's post-KEYB92 source, Pico firmware link, physical DOS6 boot, or IRQ0-enabled stability. Public GitHub currently exposes an older version of `src/bb_live.c`; the installer checks the current **local** source rather than assuming GitHub matches.
- **Unchanged by design**: Timer IRQ0 isolation, 8042/IRQ1 behavior, real DOS6 disk and keyboard behavior beyond AH=A2h, 386 protected mode, XMS and DOS/4GW support.

## Compatibility reference

Ralf Brown's Interrupt List, `INT 16h AH=A2h`:
https://delorie.com/djgpp/doc/rbinter/id/79/18.html

> AH <= 80h on return means support for 122-key keyboard functions. Therefore this normal enhanced keyboard implementation deliberately preserves AH=A2h to report no such support.
