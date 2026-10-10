# v49 FP exception frame fix

The original naked SysTick handler skipped extended FP exception frames, so the PC profiler recorded almost no samples even while SysTick was active. This version reads the integer exception frame at `SP + 72` when EXC_RETURN bit 4 is clear, otherwise at `SP`, then retrieves PC at offset 24.

Only `C:\blitzBUS\src\bb_v49_pc.h` is replaced. No changes to blitz86 or the JIT generation code.

```powershell
cd C:\blitzBUS
python .\v49-fp-fix\install_v49_fp.py --blitzbus C:\blitzBUS --check
python .\v49-fp-fix\install_v49_fp.py --blitzbus C:\blitzBUS --apply
```

Rebuild/flash using the normal `bb_live_run.ps1` invocation. Look for a growing `seq` and `mapped > 0` in `[bb-v49-pc]` reports. If sequence still grows too slowly, the root cause is not yet proven; preserve the log.

Restore: `python .\v49-fp-fix\install_v49_fp.py --blitzbus C:\blitzBUS --restore`

Not yet validated on RP2350 hardware. No guarantees of zero profile overhead.
