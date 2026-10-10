# blitzBUS SWD Capture v2 — OpenOCD Tcl RPC

Fixes v1's Telnet command echo/prompt races. Uses OpenOCD's `6666` Tcl RPC connection with `0x1A` framing and explicit `rp2350.dap.core0` selection. Attempts to resume the core after each sample, and retains partial results after Ctrl+C.

**Before capture: fix firmware build!** The supplied run log shows `.bss` SRAM overflow 38,432 bytes (562,720 of 524,288). Do not attribute captured PC `0x1001B740` to the new firmware until you successfully build, flash, and boot the latest version. The prior firmware may be running.

Terminal A: Start OpenOCD through the existing Pico SDK install:

```powershell
$ocd = "$HOME\.pico-sdk\openocd\0.12.0+dev\openocd.exe"
$scripts = Get-ChildItem "$HOME\.pico-sdk\openocd" -Directory -Filter scripts -Recurse | Where-Object { Test-Path (Join-Path $_.FullName 'target\rp2350.cfg') } | Select-Object -First 1
& $ocd -s $scripts.FullName -f interface/cmsis-dap.cfg -f target/rp2350.cfg -c 'adapter speed 1000'
```

Terminal B: Only after confirming a **successful** build and flash, run `3DBENCH` on COM5.

Terminal C:

```powershell
cd C:\blitzBUS
$tool = "$HOME\.pico-sdk\toolchain\14_2_Rel1\bin\arm-none-eabi-objdump.exe"
python .\blitz_swd_v2\swd_capture.py --count 80 --interval 0.25 --out .\logs\swd_3dbench_v2 --objdump $tool
```

Capture changes benchmark timing; keep v49f's 100 Hz SysTick data for timing comparisons. A repeating PC can mean a tight loop or a non-running benchmark; look up the address in the **matching** ELF/disassembly:

```powershell
$elf = 'C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.elf'
$addr2line = "$HOME\.pico-sdk\toolchain\14_2_Rel1\bin\arm-none-eabi-addr2line.exe"
& $addr2line -f -C -e $elf 0x1001B740
```

**No resets, writes, flashing, or program modifications.** OpenOCD's `halt`/`resume` briefly pauses the core. If OpenOCD itself has halted the core before capture, run `resume` using its Telnet port 4444 prior to starting the benchmark.
