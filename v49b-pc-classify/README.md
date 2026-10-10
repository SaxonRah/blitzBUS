# v49b PC-region diagnostic

Replaces only `C:\blitzBUS\src\bb_v49_pc.h`. Requires working v49 with FP frame handling. No changes to blitz86 or the x86 execution path. It categorizes sampled interrupted ARM PCs by memory region, prints up to 12 representative raw addresses, and retains the JIT block lookup and SysTick state report.

```powershell
cd C:\blitzBUS
python .\v49b-pc-classify\install_v49b.py --blitzbus C:\blitzBUS --check
python .\v49b-pc-classify\install_v49b.py --blitzbus C:\blitzBUS --apply
```

Run existing `bb_live_run.ps1` and `3DBENCH`, then capture `[bb-v49b-regions]`, `[bb-v49b-rawpc]`, `[bb-v49b-state]`, and `[bb-v49-pc-block]`.

To restore the original v49 header:

```powershell
python .\v49b-pc-classify\install_v49b.py --blitzbus C:\blitzBUS --restore
```

Interpretation: samples marked XIP-FLASH may mean time in flash-resident runtime or translation code. LOW-ALIAS can also be legitimate mapped execution, so region categories alone do not identify functions. The raw PC addresses let us identify whether the interrupt is recording an unexpected constant PC or mapping is incorrect. Lost samples are overwritten ring entries, not missed interrupts.

CAUTION: Experimental hardware instrumentation, not cross-compiled or hardware-verified here. Current static SRAM allocation is near capacity.
