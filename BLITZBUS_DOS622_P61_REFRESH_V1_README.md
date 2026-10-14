# blitzBUS / MS-DOS 6.22 — port 61h memory-refresh bit repair (P61_REFRESH_V1)

**2026-10-14. Diagnostic, DOS6-only, reversible Python installer — no Git patches.**

## Why this specific fix

The latest real Pico Plus 2 boot shows `KEYB INT16/AH=92` and `INT16/AH=A2` both completed, then the watchdog remains at `1016:1112` / `1016:1114`, with bytes `E4 61 24 10 3A C4`. This decodes as `IN AL,61h; AND AL,10h; CMP AL,AH`, a wait for port 61h's **bit 4** to change. On PC/AT, bit 4 reflects periodic refresh. Without this read-only signal, old code can spin forever even though the CPU/JIT executes correctly. This is the next hypothesis to test, not a claim that full DOS 6.22 is already operational.

## Scope

The installer alters only `C:\blitzBUS\src\bb_live.c` in the *existing common* `bb_v35_pit_in8` hook. The native blitz86 `IN` path delegates through this runtime hook; so does the microDOS interpreter. During opt-in DOS622 operation, it overrides **bit 4 only** of reads of I/O port `0x61`, with a signal that changes every **approximately 15 us** of monotonic hardware time. The existing lower and upper bits still come from the original handler. A bounded `[bb622-p61]` trace logs up to 8 observed bit transitions. No new memory buffers or long-lived timers are installed.

It does **not** modify `bb_live.c` opcodes/JIT, the BIOS keyboard A2/92 patches, CPU model, IRQ0 suppression, SD images, DOS2 path, PIT channel setup, PIC emulation, or port 61h write semantics. It is a minimal diagnostic fix, not a complete PC/AT system-control emulation.

## Exact source safeguard

Expected input: `src/bb_live.c` **91,655 bytes**, SHA-256 `b02d3e80907d22e7d0ab9779cf1bbba01dfae0836ff631cd9750e073d16c46c9`, directly from the latest successful V3 `apply`/`verify` and build log. Any local source change refuses the installation; do **not** weaken the guard. The installer includes V3's active SHA-manifest walker directly, avoiding the V1/V2 format assumptions. It can adjust nested `installed/new/after/parent_after` checksum fields (including the V3 state), preserving original/old/before digest fields, JSON format, and byte-exact backups.

## Installation — Windows PowerShell

Extract `BLITZBUS_DOS622_P61_REFRESH_V1.zip` and copy **`bb_dos622_p61_refresh_v1.py`** into `C:\blitzBUS`.

```powershell
cd C:\blitzBUS
python .\bb_dos622_p61_refresh_v1.py selftest
python .\bb_dos622_p61_refresh_v1.py probe
```

**Only if `probe` passes:**

```powershell
python .\bb_dos622_p61_refresh_v1.py apply
python .\bb_dos622_p61_refresh_v1.py verify
python .\bb_dos622_keyba2_v3.py verify
python .\bb_dos622_keyb92_v1.py verify
python .\bb_dos622_irq0_isolation_v1.py verify
```

If any verify fails, stop; do not flash. `restore` is available while the new V1 state is consistent. `recover` is only for interrupted writes and refuses unrelated edits. Unwind installers newest first, never restore an older installer while a dependent newer patch remains.

## Hardware test

Keep the **same** existing DOS6-specific IRQ0 diagnostic suppression, `BB_CPU=286`, native cache, LCD and SD settings. The test uses `DOS622.TXT=1`, a read-only `DOS622.IMG`, and keeps `BOOT.IMG` as the unaffected DOS2 fallback.

```powershell
cd C:\blitzBUS
$env:BB_HOT_THRESHOLD = "32"
$env:BB_EVICT_CHUNK = "4096"
$env:BB_EVICT_ROOM = "2048"
$env:BB_BBUF = "1"
$env:BB_CODE_KB = "232"
$env:BB_CPU = "286"
$env:BB_SD_BOOT = "1"
$env:BB_LCD_PERI_HZ = "150000000"
$env:BB_LCD_SPI_HZ = "75000000"
$env:BB_LCD_LACE = "1"

powershell -NoProfile -ExecutionPolicy Bypass -File `
    .\scripts\bb_live_run.ps1 `
    -MicroDOS C:\microDOS `
    -Blitz86 C:\blitz86_v2 `
    -Port COM5 `
    -Seconds 180
```

Look for both `[bb622-keyba2]` and subsequent `[bb622-p61]` logs with `refresh=0` and `refresh=1`. The definitive progress signal is **that watchdog CS:IP leaves the tight loop at `1016:1112–1114`**, and guest text/BIOS activity resumes. Getting a `A:\>`/`C:\>` prompt remains the objective, not something this installer itself can guarantee. If it remains in the loop with no `[bb622-p61]` output, another I/O handler may have intercepted port `61h` before this wrapper; capture and inspect that routing rather than altering the refresh period blindly.

## Roll back (V1 only)

```powershell
python .\bb_dos622_p61_refresh_v1.py restore
python .\bb_dos622_keyba2_v3.py verify
```

The installer keeps all changed files' original bytes, hashes, and a recovery manifest before writes, and restores the complete parent SHA chain byte-exactly.

## Local tests completed

- LF/CRLF/mixed newline source insertions, parent manifest SHA cascade including nested V3 state, byte-exact rollback.
- Refuses missing native/interpreter hooks and unexpected function layout.
- C11 compiled runtime contract: bit4 toggles at simulated 15-us increments; lower/upper seven bits retained; DOS2 reads and non-port-61 I/O unchanged.

**Not tested:** the user's local repository `probe`, Pico firmware link/flash, or a real DOS6 boot after this fix. Those require the user's hardware and source tree.
