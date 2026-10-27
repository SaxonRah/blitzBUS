# blitzBUS DOS 6.22 — VGA12/30 (400 scan lines) V1

## Verified hardware observation

The 2026-10-14 03:13 Pico Plus 2 run successfully flashed after an initial BOOTSEL connection failure, built `src/bb_live.c` (93,946 bytes; SHA-256 `12c76d54018be0e173b34b97aec5424cb4c172d113bcec4b37ec945ab52f294f`), and passed the prior VGA cursor BIOS request:

```text
[bb622-vga12] INT10 AH=12 BL=34 cursor_emulation=1 out-ax=1212
[bb-trace] INT10 handled ax=1212 cs:ip=2600:0144 sp=33D0
[bb-trace] INT10 enter n=24 ax=1202 cs:ip=2600:014B sp=33D0
[bb622-missing-bios] unhandled INT 10 AX=1202 BX=0030 CX=0008 DX=92E8 at 2600:014B; null IVT, stopping safely
```

The new unsupported call is **INT 10h AH=12h BL=30h AL=02h**. On VGA hardware, AL=02h selects **400 scan lines for the next text mode set**, and successful support is indicated by returning **AL=12h**. This is consistent with the existing 80×25 / 400-line text mode model. The caller's AH remains 12h, yielding `AX=1212h`.

## What this patch changes

- Adds an opt-in DOS 6.22-only helper in `src/bb_live.c`, servicing only **AH=12h, BL=30h, AL=02h**.
- Inserts the helper between the earlier `bb622_vga12_34` handler and `bb_vga_int10` in **both native and interpreter** interrupt hooks.
- Returns `AL=12h`, preserves BX/CX/DX/ES/BP/flags, and logs up to eight calls.
- **Does not claim 200- or 350-line modes are supported.** Other AL values and subfunctions fall through to existing handling.
- Does not change video timing, keyboard, ROM image, SD boot, JIT, PIT/PIC, port 61h, or diagnostic IRQ0 isolation.
- Gates on `bb_sd_dos622_active()` so the older DOS2 path is unchanged.
- Carries installed/source SHA values through active parent manifests (including VGA12/34) while keeping all historical backup checksums untouched; has exact-byte rollback.
- **Refuses** any source other than the 93,946-byte SHA shown above; no force-apply flag is provided.

This is a narrow compatibility unblocker, not yet a complete VGA BIOS implementation. **The guest boot result after installing it has not been tested on your Pico.**

## Installation

Unzip the archive; copy `bb_dos622_vga12_30_v1.py` into `C:\blitzBUS` (alongside the older installer scripts, not inside `src`).

```powershell
cd C:\blitzBUS
python .\bb_dos622_vga12_30_v1.py selftest
python .\bb_dos622_vga12_30_v1.py probe
```

If `probe` succeeds, apply and verify:

```powershell
python .\bb_dos622_vga12_30_v1.py apply
python .\bb_dos622_vga12_30_v1.py verify
python .\bb_dos622_vga12_34_v1.py verify
python .\bb_dos622_p61_refresh_v1.py verify
python .\bb_dos622_keyba2_v3.py verify
python .\bb_dos622_keyb92_v1.py verify
python .\bb_dos622_irq0_isolation_v1.py verify
```

Do **not** run `apply` if `probe` fails. Share the diagnostic instead.

## Pico test

Keep your previous DOS6 settings:

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

Expect this once the VGA initialization reaches the formerly failing call:

```text
[bb622-vga1230] INT10 AH=12 BL=30 scanlines=400 next-mode out-ax=1212
```

The important goal is movement past `2600:014B`. If the same safe-stop occurs or another BIOS function is missing, provide the console log; don't interpret the stop as an independent USB-keyboard failure.

A missing BOOTSEL device during flashing is a *separate host/USB bootloader issue*. The first flash in your latest log failed to locate the RP2350; the second attempt succeeded. Ensure the board is actually in BOOTSEL before a failed flash retry.

## Exact rollback

If this is the topmost installed layer:

```powershell
python .\bb_dos622_vga12_30_v1.py restore
```

The `recover` option is only for an interrupted or incomplete `apply`. Do not restore an earlier layer before removing its newer dependent installers in reverse order. All backup data is SHA-checked before restoration.

## Tests

Selftest covers LF, CRLF and mixed line endings; unique interrupt-hook anchors; unsupported calls; DOS6 gating; preservation of VGA12/34; source, parent metadata and byte-for-byte rollback; a C11 native/interpreter contract when a compiler is installed. These local tests passed. Hardware confirmation remains outstanding.

## Reference

Video Seven VGA Technical Reference, "Int 10 — Function 12 — Subfunction 30 — Select Scan Lines"; also the 1999 Chips & Technologies 69030 VGA BIOS OEM Reference Guide, section 5.3.
