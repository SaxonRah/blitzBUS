# blitzBUS DOS 6.22 — KEYB INT 16h AH=A2h fix, V2

**Date:** 2026-10-14  
**Target:** `C:\blitzBUS\src\bb_live.c` immediately following the already installed `bb_dos622_keyb92_v1.py` fix.  
**Delivery:** complete Python installer and exact recovery logic; **not a Git patch**.

## Why V1 failed on your actual source

Your output showed:

```text
python bb_dos622_keyba2_v1.py selftest  # PASS (small synthetic handlers)
python bb_dos622_keyba2_v1.py probe     # ERROR: Cannot prove A2h handler precedes unknown-service rejection
python bb_dos622_keyba2_v1.py apply     # same error, no changes
python bb_dos622_keyba2_v1.py verify    # no state manifest because apply never ran
```

V1 inserted code **in memory** for `probe`, then attempted to find the old `if (ah!=0x00u...)` fallback within a **fixed 1,300-byte window** from the function start. The installed AH=92h support made the handler larger; that location-dependent proof failed. The failure was in the installer’s acceptance test, **not evidence of a firmware or guest DOS fault**. No repository files were changed by those failed commands.

V2 replaces the brittle search with a local ordering proof: the `uint8_t ah=(uint8_t)(*ax>>8);` declaration must be the **first source statement** of the one shared `bb_v22_keyboard()` function; V2 inserts immediately afterward, before any pre-existing dispatch or unsupported-service return. It **refuses** to patch if some executable code precedes the declaration. This proof does not depend on where the old rejection is located or how it is spelled.

The new branch handles **only** DOS622-opted-in `INT 16h AH=A2h`, leaving `AX` (including `AH=A2h`), FLAGS, IP, rewind, and other registers unchanged, thereby not advertising 122-key services. Existing AH=92h behavior is preserved. The non-DOS622 path passes through unchanged.

## Install V2

1. Extract `BLITZBUS_DOS622_KEYBA2_V2.zip`.
2. Copy **`bb_dos622_keyba2_v2.py`** to `C:\blitzBUS`.
3. Run:

```powershell
cd C:\blitzBUS
python .\bb_dos622_keyba2_v2.py selftest
python .\bb_dos622_keyba2_v2.py probe
python .\bb_dos622_keyba2_v2.py apply
python .\bb_dos622_keyba2_v2.py verify
python .\bb_dos622_keyb92_v1.py verify
```

**Do not** run V1 `verify`: it is expected to fail because V1 never applied. Leave the V1 script alone if desired; V2 has a separate `.bb_dos622_keyba2_v2_state` and source marker.

`probe` and `apply` require `src/bb_live.c` to be **90,997 bytes** with SHA-256 beginning **`99c40b35f00e`**, matching the actual source in the latest handoff (not the lagging public GitHub copy). The installed KEYB92 parent checksum manifest must match the pre-patch SHA. All other `.bb_dos622_*_state/manifest.json` files recording that exact source SHA are updated too, using byte-exact backups and per-file atomic replacement. An unexpected state is a **hard stop**, not a reason to turn off verification. No boot images are modified.

## Run on Pico 2 after `verify` PASS

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

When `Starting MS-DOS...` appears, press Enter. Look for:

```text
[bb622-keyb92] KEYB INT16/AH=92 in-ax=9200 out-ax=8000 (IBM enhanced keyboard)
[bb622-keyba2] KEYB INT16/AH=A2 unsupported 122-key; AX=A200 preserved
```

**Expected**: no further `unhandled INT 16 AX=A200`. We cannot claim a completed DOS6 boot until the Pico capture shows an interactive command prompt (`VER`, `DIR`, `MEM`). Existing DOS6-only IRQ0 suppression is *not* changed and still requires repair before the final boot milestone. 386, XMS, and DOS/4GW remain separate later milestones.

## Exact reversal

```powershell
cd C:\blitzBUS
python .\bb_dos622_keyba2_v2.py verify
python .\bb_dos622_keyba2_v2.py restore
python .\bb_dos622_keyb92_v1.py verify
```

An interrupted install can be unwound with `python .\bb_dos622_keyba2_v2.py recover`, but only if the affected files are still at one of the recorded SHA hashes. This rejects unrelated edits. Do not invoke `recover` during normal usage.

## Testing and limits

V2 self-tests include LF, CRLF, mixed line endings, source and parent SHA checking, atomic install/restore, installed-marker duplication guard, **regression for a KEYB92-expanded handler with the old fallback more than 1,300 bytes away**, refusal of an earlier executable statement, and a compiled C11 register contract (when a host C compiler is available).

The V2 source was **not compiled against your private Windows working tree or flashed onto a Pico** in this environment. The SHA-pinned real source must pass `probe` before changing anything, then your Pico run determines actual behavior.
