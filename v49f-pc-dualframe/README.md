# v49f — dual candidate frame profiler

v49c hardware probe showed valid `selected[6]` / `selected[7]` pairs even though
EXC_RETURN `FFFFFFE9` has bit 4 cleared (FType=0, FP context allocated).
This is **not** evidence that FType=1. v49f validates the base candidate
first and tries the `selected[24]`/`[25]` extended offset only as fallback
when FType is zero. It reports both and rejects non-executable PCs.

## Install

Extract ZIP into `C:\blitzBUS`, then:

```powershell
cd C:\blitzBUS
python .\v49f-pc-dualframe\install_v49f.py --blitzbus C:\blitzBUS --hz 100 --check
python .\v49f-pc-dualframe\install_v49f.py --blitzbus C:\blitzBUS --hz 100 --apply
```

Uses the existing live runner. To compare 1000 Hz, restore, then apply with
`--hz 1000` and reflash. Backups are
`src\bb_v49_pc.h.before_v49f` and `src\bb_live.c.before_v49f`.

```powershell
python .\v49f-pc-dualframe\install_v49f.py --blitzbus C:\blitzBUS --restore
```

Look for `[bb-v49f-validation]` base/fp-fallback/rejected counters.
If FPS varies, run 3DBENCH multiple times *within one interactive session*
(without re-running `bb_live_run.ps1`, which reflashes on each invocation).
Record failures separately from successful scores.

Notes: The interrupted PC is not guaranteed to map to a current JIT cache
entry after code flushing. No JIT execution logic is changed. This is a
candidate-selection experiment, not a final Armv8-M frame unwinder.
