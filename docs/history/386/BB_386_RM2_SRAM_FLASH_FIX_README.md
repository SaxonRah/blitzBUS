# blitzBUS / blitz86 — RM2 SRAM overflow fix v1

## The observed failure

The supplied `bb_live_run.ps1` build **compiled** `src/interp.c`, then **failed during linking**. Linker report:

| Region | Used | Capacity |
|---|---:|---:|
| FLASH | 693,284 bytes | 16 MiB (4.13%) |
| PSRAM | 4,235,296 bytes | 8 MiB (50.49%) |
| RAM | **525,960 bytes** | **524,288 bytes** (100.32%) |

`.heap` overlaps the second core's reserved stack. Over the RAM limit by **1,672 bytes**. No UF2 was generated. This is **not a code-cache eviction bug** or an RM2 compiler error.

## Fix

`bb_386_rm2_flash_sram_v1.py` is a guarded, reversible **complete-file editor** (not a Git patch). It changes exactly four source files in your local `C:\blitz86_v2` checkout:

- `src/i386_rm0.inc`
- `src/i386_rm1.inc`
- `src/i386_rm2.inc`
- `src/interp.c`

All **26 386-only interpreter helper definitions** are explicitly marked `noinline` with a `.text.bb386_flash` section, so GCC cannot inline them into a `.time_critical` RAM routine. The **386-only upper-half-preservation path** of `b86_step()` is similarly isolated in XIP flash. Three *rare* 286 helper families—DAA/DAS, AAA/AAS, and the 286 `0F` descriptor/MSW instruction handler—move out of RAM as a little more link margin.

**Unchanged:** 286 `b86_step_internal()` remains `B86_HOT`; the normal 286 `b86_step` branch stays in RAM; JIT, Thumb-2 emitter, native RCL/RCR, eager unchaining, hot threshold, memory map, PSRAM, and **232 KiB code-cache allocation** remain unchanged. `BB_CPU=286` remains the recommended regression mode.

At this stage, the 386 emulator remains interpreter-only and will be slower than 286 native code. Correctness and SRAM budget are the goals.

## Installation

Extract both files from the ZIP into `C:\blitzBUS`. RM0, RM1 and RM2 must **still be installed**; this fix layers on top of them.

```powershell
cd C:\blitzBUS
python .\bb_386_rm2_v1.py verify
python .\bb_386_rm2_flash_sram_v1.py selftest
python .\bb_386_rm2_flash_sram_v1.py probe
python .\bb_386_rm2_flash_sram_v1.py apply
python .\bb_386_rm2_flash_sram_v1.py verify
```

After applying this layer, `bb_386_rm2_v1.py verify` **will detect a SHA mismatch**, as expected, because the source has intentionally changed. To restore or modify RM2, restore **this** layer first.

### Build / test

```powershell
cd C:\blitzBUS
$env:BB_CPU = '286'
$env:BB_CODE_KB = '232'
$env:BB_HOT_THRESHOLD = '32'
$env:BB_EVICT_CHUNK = '4096'
$env:BB_EVICT_ROOM = '2048'
$env:BB_NO_CHAIN = '0'

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run.ps1 `
  -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

**Expected linker outcome:** RAM **under 524,288 bytes** with no `.heap`/`.stack1_dummy` overlap. Exact SRAM savings can only be determined with your actual Pico toolchain and linker layout; **this fix is not yet verified on your hardware**.

In DOS:

```dos
C:
CD \BENCH
RCXTEST
T2ECPU
3DBENCH
```

Targets: `RCXTEST PASS 64 / 64`, `T2E CHECKSUM=8642`, and **3DBench 58.8**.

If SRAM still exceeds the limit, send the new linker report and (if available) `C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.map` so we can move the specific remaining RAM functions. **Do not reduce the JIT cache or edit the linker script as a first resort.**

### Exact restoration

```powershell
cd C:\blitzBUS
python .\bb_386_rm2_flash_sram_v1.py verify
python .\bb_386_rm2_flash_sram_v1.py restore
python .\bb_386_rm2_v1.py verify
```

The script backs up original bytes with SHA-256 and refuses to overwrite unexpected changes. It neither commits to GitHub nor changes the old RM0/RM1/RM2 installer backups.

### Validation already run

- Script selftest: unique anchors, LF and CRLF, install, verify, idempotency guard, exact restore.
- GCC `-O3` mock compile/run: 286 branch and 386 upper-register-preservation branch correctly execute.
- `objdump -h` confirms `.text.bb386_flash` is separate from `.time_critical.blitz86` in the mock object.
- **Full Pico/SDK linker test is pending on Windows hardware.**
