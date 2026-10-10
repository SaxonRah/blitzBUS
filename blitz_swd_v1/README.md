# blitz86 / blitzBUS SWD capture v1

The Debug Probe's **COM4 is UART**, not the SWD debug link. OpenOCD uses the **CMSIS-DAP USB interface** of the same probe. These must be connected with SWDIO, SWCLK and GND to the Pico Plus 2's debug pins. COM5 can remain the live blitzBUS DOS console.

## Before starting

1. Verify `openocd --version` and `arm-none-eabi-objdump --version` in Windows PowerShell. If either isn't on PATH, locate it in `.pico-sdk` or your installed toolchain; do not substitute COM4.
2. Confirm SWD wiring and common ground. Leave debugger reset/flash operations disabled.
3. Run OpenOCD in **PowerShell window A**:

   ```powershell
   openocd -f interface/cmsis-dap.cfg -f target/rp2350.cfg -c "adapter speed 1000"
   ```

   It should report RP2350 Cortex-M33 and telnet port 4444. If your OpenOCD lacks `rp2350.cfg`, use a Pico-SDK-compatible/Raspberry Pi OpenOCD build. Do not use `rp2040.cfg` for RP2350.

4. Run the existing `bb_live_run.ps1` in **PowerShell window B**, leaving it on COM5, and start 3DBENCH.
5. In **PowerShell window C**, run:

   ```powershell
   cd C:\blitzBUS
   python .\blitz_swd_v1\swd_capture.py --count 80 --interval 0.25 --out .\logs\swd_3dbench
   ```

   This produces `samples.csv`, `ranked_pcs.txt`, `instructions.txt`, and one 64-byte binary snapshot for each successfully read code PC.

## Warnings and interpretation

- This script **HALTS and RESUMES** the core for each sample. This alters execution timing, therefore do **not** use the resulting 3DBENCH FPS as a speed measurement.
- SWD may be unavailable if the target's security/debug restrictions disable it. OpenOCD may not attach until the probe and target are powered and wired correctly.
- OpenOCD versions differ in telnet formatting and SMP core selections; this script is a diagnostic prototype. If PC parsing fails, include `openocd_banner.txt` and logs when reporting.
- SWD memory capture at JIT locations is useful even after JIT invalidation; each binary snapshot is captured while halted. A dynamically translated code buffer can change between samples.
- Read-only SWD commands used: `halt`, `reg pc`, `mdb`, `resume`. No programming or rewriting.
- If target freezes under repeated halts, reduce `--count`, increase `--interval`, or stop sampling. The `finally` clause attempts `resume` after each halt, but disconnects can prevent it; manually issue `resume` in OpenOCD if needed.
- This tool cannot produce zero-interference instruction traces. Use v49f's 100 Hz onboard sampler for robust hotspot frequencies; the debugger is for examining machine-code snapshots.
- The supplied `--elf` arg is documentary in this version; `arm-none-eabi-addr2line` can map linked functions but will not identify dynamically generated JIT blocks by itself.
