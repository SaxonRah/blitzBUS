# blitzBUS — DOS 6.22 VGA cursor-emulation BIOS (VGA12_34_V1)

## Root cause found from 2026-10-14 03:03 capture

DOS6 proceeds past KEYB AH=92h, AH=A2h and the port 61h DRAM-refresh wait. The last 8 port61 traces show alternating refresh bits (0, 1), and keyboard initialization installs INT 09/2F handlers.

The guest then invokes `INT 10h AX=1200h BX=0034h` from `2600:0144`. The current VGA BIOS adapter cannot handle `AH=12h BL=34h`, so the `bb622-missing-bios` fail-safe stops execution. Once that stops the serial console's device, keyboard input is no longer accepted; this is a consequence, not an independent USB hardware failure.

The new function is IBM VGA `INT 10h AH=12h BL=34h`: select alphanumeric cursor emulation (`AL=0` enable; `AL=1` disable). As specified in the IBM VGA BIOS reference, report supported by returning `AL=12h`. It does **not** implement detailed cursor shape scaling yet; this is the minimum needed to unblock the startup probe. Unsupported `AH=12h` subservices continue through existing behavior.

## Exactly what the patch does

- Modifies only `src/bb_live.c`; adds one helper used by **both** the native and interpreter INT10 paths.
- Intercepts DOS6-only `AH=12h BL=34h AL=00h/01h` and returns `AX=1212h`. Preserves BX/CX/DX/ES/BP/flags and normal existing return-path bookkeeping.
- No updates to `bb_vga.c`, IRQ0, PIC, PIT, JIT, DOS images, microDOS, or blitz86 source.
- Has no effects on DOS2 (`bb_sd_dos622_active()` gate); other INT10 calls follow existing handler.
- Updates active dependency-checksum metadata (including installed Port61 and KEYB92 state), with exact-byte backups and reverse-order restore.
- Refuses source revisions other than the exact build from the attached 03:03 capture: `92909` bytes, SHA256 `2b37d15bf75e0af512d7ba716c73512df37039ca4ce897bcbeeacaf94a972cf6`.
- Existing install scripts still work; **do not run `restore` on an earlier layer while newer dependent layers remain installed**. Restore in reverse order first.

## Install

Extract the ZIP. Copy `bb_dos622_vga12_34_v1.py` into `C:\blitzBUS`, **not** inside `src`.

```powershell
cd C:\blitzBUS
python .\bb_dos622_vga12_34_v1.py selftest
python .\bb_dos622_vga12_34_v1.py probe
```

If and only if `probe` passes:

```powershell
python .\bb_dos622_vga12_34_v1.py apply
python .\bb_dos622_vga12_34_v1.py verify
python .\bb_dos622_p61_refresh_v1.py verify
python .\bb_dos622_keyba2_v3.py verify
python .\bb_dos622_keyb92_v1.py verify
python .\bb_dos622_irq0_isolation_v1.py verify
```

Retain the hardware settings from the successful previous build:

```powershell
$env:BB_HOT_THRESHOLD = '32'
$env:BB_EVICT_CHUNK = '4096'
$env:BB_EVICT_ROOM = '2048'
$env:BB_BBUF = '1'
$env:BB_CODE_KB = '232'
$env:BB_CPU = '286'
$env:BB_SD_BOOT = '1'
$env:BB_LCD_PERI_HZ = '150000000'
$env:BB_LCD_SPI_HZ = '75000000'
$env:BB_LCD_LACE = '1'

powershell -NoProfile -ExecutionPolicy Bypass -File `
    .\scripts\bb_live_run.ps1 `
    -MicroDOS C:\microDOS `
    -Blitz86 C:\blitz86_v2 `
    -Port COM5 `
    -Seconds 180
```

## Expected next diagnostic

```text
[bb622-p61] read=... refresh=1 ...
[bb622-p61] read=... refresh=0 ...
[bb622-vga12] INT10 AH=12 BL=34 cursor_emulation=1 out-ax=1212
```

The actual test is whether DOS continues beyond `2600:0144`. Another `bb622-missing-bios` line would identify the next unsupported BIOS function. Never assume a DOS prompt until observed.

## Rollback

```powershell
python .\bb_dos622_vga12_34_v1.py restore
```

The `recover` option is for incomplete/interruptible apply state **only**, with SHA verification of all known bytes. `restore` normally verifies exact installed hashes first. Prior P61/KEYBA2 layers should be restored only after restoring VGA12.

## Tests

The installer self-tests LF, CRLF and mixed line endings; refuses duplicated or missing hooks; verifies propagation through different parent manifest JSON shapes and byte-identical restoration; compiles/runs a C11 test for native/interpreter calls, DOS6/DOS2 selection, AX return value, and unsupported BIOS probes when a local C compiler is installed.

Local tests passed. **Pico build and guest boot after this change have not been validated.**

## Reference

IBM PS/2 and PC BIOS Interface Technical Reference (April 1987) defines `INT 10h AH=12h BL=34h` with `AL=00h` enable/`01h` disable cursor emulation; `AL=12h` indicates function supported. Ralf Brown's Interrupt List and ReactOS FreeLdr agree.
