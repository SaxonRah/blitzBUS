# blitz86 EA Immediate-12 First Pass (opt-in)

Source captured 2026-10-09 from local `C:\blitz86_v2`. This is a **narrow effective-address emitter optimization**, not yet a general direct-RAM bypass.

`be_t2.c` is a **complete replacement file**, no git patch. Installer validates SHA256 and preserves a backup. No existing project files are overwritten unless their contents match the provided snapshot.

### 1. Install

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\blitz_ea_imm12_v1.zip" C:\blitzBUS -Force
.\blitz_ea_imm12_v1\install.ps1 -Mode On
```

### 2. Enable / disable build feature

Your current firmware compiles `be_t2.c` as part of the `blitzbus_pico_b86_dos` CMake target in `C:\microDOS\pico\CMakeLists.txt`. Add this CMake line **after target creation** in the opt-in target section:

```cmake
target_compile_definitions(blitzbus_pico_b86_dos PRIVATE B86_EA_IMM12_FAST=1)
```

To test original behavior, change to `B86_EA_IMM12_FAST=0` (or remove that one line), then rebuild. This is compile-time, not a PowerShell environment variable.

### 3. Build and benchmark

```powershell
cd C:\blitzBUS
$env:BB_LCD_PERI_HZ='150000000'
$env:BB_LCD_SPI_HZ='75000000'
$env:BB_LCD_LACE='1'
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

Validate DOS boot, DOS2TEST, MDSTRESS and 3DBENCH. Compare code-cache use, emitted code size, wall time and benchmark score, preferably multiple runs. Do not infer performance gains until measured.

### What it changes

For an absolute x86 memory operand (no index/base registers), with unsigned 16-bit displacement 0..4095, replace two 32-bit Thumb-2 instructions (MOVW + ADD) with one (MOV or ADDW). All address-page translations, write SMC checks, 8086 modulo-offset behavior, other-address cases, and flags are preserved. Translated blocks with these operands save one Thumb-2 instruction and 4 bytes. Other blocks are unaffected.

### Limitation

The general JIT address translation uses runtime `cpu->pt` deltas (`be_ea`/`ea_translate`), and writes need codemap invalidation (`be_store`). Safely bypassing this machinery needs a guarded mapping contract or invalidation epoch and further testing; this package deliberately does not remove it.
