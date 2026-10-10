# blitzBUS JIT-focused SWD capture v3

This is a **new standalone script**; it does **not** modify the Pico firmware, CMake, JIT, or v49f. It reuses your working Raspberry Pi Debug Probe/OpenOCD Tcl RPC connection.

## What changed from v2

- Records up to 512 bytes around a sampled JIT PC rather than 64 bytes around every random PC.
- Filters addresses to the existing `bb_code` range 0x2002A040..0x2006403F, derived from your current linker map.
- Uses chunked 64-byte OpenOCD memory reads to avoid truncated Tcl results.
- Writes one CSV, raw binary windows, disassembly, and summary.
- Saves captured data even on Ctrl+C; refuses to overwrite prior capture directories.
- Resumes the target after each halt; a SWD debugger can still perturb execution/timing.

## PowerShell window arrangement

**First** use your normal `bb_live_run.ps1` with `$env:BB_LCD_LACE="1"`, and **start 3DBENCH**. OpenOCD must be running in another terminal and listening on Tcl port 6666. Run the command below in the third terminal **only while 3DBENCH is drawing**.

```powershell
cd C:\blitzBUS
$tool = "$HOME\.pico-sdk\toolchain\14_2_Rel1\bin\arm-none-eabi-objdump.exe"
python .\blitz_jit_audit_v3\jit_capture_v3.py `
    --attempts 160 `
    --max-blocks 24 `
    --interval 0.10 `
    --out .\logs\swd_jit_v3_first `
    --objdump $tool
Compress-Archive .\logs\swd_jit_v3_first\* .\logs\swd_jit_v3_first.zip -Force
```

Upload the resulting ZIP. Every window contains the *actual live bytes*, not compiled/static source. The `.elf` cannot decode JIT-generated code directly because the JIT writes those instructions at runtime.

## Limitations

A 512-byte window does not necessarily contain a whole block; blocks can be longer or shorter. Thumb-2 instructions can be 16 or 32 bits; disassembling from an arbitrary 4-byte alignment before a sampled PC can show spurious instructions until true instruction alignment is recovered. This capture is diagnostic, not proof of an optimization. Accurate guest `CS:IP` mapping still requires the v49f block metadata, or a future code-generation metadata export.

The cache range is based on your current map. If `bb_code` moves after other firmware changes, run `Select-String C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.map -SimpleMatch '.bss.bb_code'` to update `--jit-start` / `--jit-size`.
