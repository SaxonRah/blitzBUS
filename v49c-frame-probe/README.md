# v49c: Raw Cortex-M33 exception-frame probe

This is a **diagnostic build**, NOT a hot-PC profile. It replaces the v49b PC histogram with raw captured EXC_RETURN and selected-stack frame words. Do not interpret `bb-v49c-basic` as validated PC yet.

## Install

Extract ZIP to `C:\blitzBUS`, yielding `v49c-frame-probe`.

```powershell
python .\v49c-frame-probe\install_v49c.py --blitzbus C:\blitzBUS --check
python .\v49c-frame-probe\install_v49c.py --blitzbus C:\blitzBUS --apply
```

Use the normal `bb_live_run.ps1` command and run `3DBENCH`. Send console output with `[bb-v49c-*]` lines. No need to run long: 3–5 reports during the render workload suffice.

## Interpretation

Each line prints EXC_RETURN, MSP, PSP, selected exception stack pointer, basic frame words 0–7 and, only when EXC_RETURN[4]=0, extended frame words 18–25. The `T=` flag checks the xPSR Thumb bit but **does not establish correctness** by itself. Observe whether the candidate PC is in executable memory and plausible across consecutive captures. Frame layout could also involve security-state and callee-register stacking; this probe records `sec=` as an initial clue.

Each ISR updates a counter at 1 kHz and captures a raw frame once per 256 events. All printing occurs outside the exception handler. No guest behavior or JIT translator code is changed. The old v49b fake region and JIT hotspot reports are intentionally removed.

## Restore

```powershell
python .\v49c-frame-probe\install_v49c.py --blitzbus C:\blitzBUS --restore
```

**Safety:** Requires byte-identical v49b source. Makes a full backup and refuses to overwrite an existing one. The Pico SDK build and hardware have not been tested here. Potential Cortex-M33 exception stacking/security corner cases remain; hardware test may fault, in which case restore.
