# blitzBUS DOS 6.22 — KEYB INT 16h AH=A2h compatibility installer V3

**14 October 2026** · **No Git patches** · **Real Pico build not performed**

This is a *replacement for V1 and V2*, both of which failed during `probe`, without applying anything. The V3 change to C is the same narrowly scoped DOS622-only AH=A2h handler used in V2; the improvement is safe updating of chained installer metadata.

## What failed in V2

```
ERROR: Unexpected parent manifest shape: C:\blitzBUS\.bb_dos622_heap_rescue_v1_state\manifest.json
```

V2 assumed *every* parent manifest stores the current source hash under `files["src/bb_live.c"]["installed"]`. The older installer history mixes formats, including `new` and `after`. It also includes `.bb_dos622_boot_diag_v1_state/repair.json` with `parent_after`, which records the checksum of another metadata JSON file and changes when that file is updated. Updating only the source hashes would break chained verification.

V3 scans only active `manifest.json` and `repair.json` inside the `.bb_dos622_*_state` directories. It updates SHA-256 strings **only** in recognized current/installed/new/after keys. It then **cascades** changed JSON-file digests into metadata that tracks those files, until stable. It does not reserialize JSON: byte counts, line endings, indentation, order, and unrelated content are unchanged. **Old/original/before/backup fields and historical `parent_before.json` snapshots stay untouched.** Unrecognized checksum fields cause `probe` to refuse installation.

The source guard additionally requires `src/bb_live.c` to match the previously captured **90,997 bytes** and SHA-256 beginning `99c40b35f00e`. Source anchors and existing KEYB92 marker must match. V1/V2/V3 insertion duplication is rejected. All changed files get SHA-checked byte-exact backups before any write, using per-file atomic replaces, with `recover` for interrupted installs.

## Install

Extract `BLITZBUS_DOS622_KEYBA2_V3.zip`, then copy **`bb_dos622_keyba2_v3.py`** to `C:\blitzBUS`. Run PowerShell:

```powershell
cd C:\blitzBUS
python .\bb_dos622_keyba2_v3.py selftest
python .\bb_dos622_keyba2_v3.py probe
```

**Read the entire `probe` report before applying.** It should show the source `90997 -> 91640` bytes (with the exact output size determined by the newline of your local source), and a list of the actual changed metadata files. All paths in this list should belong to the existing `.bb_dos622_*_state` chain. If it emits `ERROR`, no repository files were modified: provide the diagnostic output and the relevant `manifest.json` or `repair.json` so the format can be reviewed; don't force the update or manually change checksums.

Only after `PROBE PASS`:

```powershell
python .\bb_dos622_keyba2_v3.py apply
python .\bb_dos622_keyba2_v3.py verify
python .\bb_dos622_keyb92_v1.py verify
python .\bb_dos622_irq0_isolation_v1.py verify
```

If a parent installer `verify` fails **after V3 applies**, stop before building/booting; preserve the output and use V3 `restore` to return to the byte-exact pre-A2h state. The installer itself checks the new data and backups, but only the original parent scripts can fully validate their own additional invariants.

## Run the Pico hardware test after every verify passes

Keep the known diagnostic `BB_CPU=286`, native 232 KiB code cache, and **DOS622-only** IRQ0 isolation configuration:

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

After `Starting MS-DOS...`, type Enter. The expected new diagnostic is:

```
[bb622-keyba2] KEYB INT16/AH=A2 unsupported 122-key; AX=A200 preserved
```

This means the A2h handler ran, **not** that MS-DOS 6.22 successfully booted. A successful milestone requires an actual interactive prompt and repeated `VER`, `DIR`, `MEM` tests. Restoring real IRQ0 delivery, then 386/XMS/DOS extender compatibility, remain subsequent milestones.

## Exact restore

```powershell
cd C:\blitzBUS
python .\bb_dos622_keyba2_v3.py verify
python .\bb_dos622_keyba2_v3.py restore
python .\bb_dos622_keyb92_v1.py verify
```

If an install was interrupted, `python .\bb_dos622_keyba2_v3.py recover` restores only files that still match their recorded original or installed hashes; it rejects unrelated edits.

## V3 local test coverage

* Four LF/CRLF/mixed-source cases, full apply/verify/restore.
* Parent formats with `installed`, `new`, `after` and `parent_after` fields.
* Chained checksum: source -> IPL manifest -> boot-diagnostic record -> newer-stage manifest.
* Protection of old/original/before metadata and immutable historical snapshots.
* Rejection of unrecognized digest keys and early executable code.
* Regression for expanded KEYB92 function beyond V1's 1,300-byte search window.
* Compiled C11 A2h contract, AX/FLAGS/IP/rewind, existing AH=92h, non-DOS622 gate (when a C compiler is available).

These are **local synthetic tests**. Your complete Windows repository and Pico hardware are not present here, so real-tree `probe` and hardware boot remain unverified.
