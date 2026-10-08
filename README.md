# blitzBUS v0.7.6.2 — JIT counter-gate correction

This overlay replaces only `src/bb_live.c` and `src/bb_live.h`. It retains the v0.7.6.1 installer, LCD, COM console, reference-first execution, and diagnostics.

The previous adapter treated `B86JitStats.guest_insns` incrementing by exactly one as a mandatory condition. The prior hardware log showed `B86_BUDGET` (3), correct next IP, but `delta=0` on the fourth candidate (CLD). `guest_insns` is diagnostic telemetry; it is not a reliable single-dispatch correctness oracle.

v0.7.6.2 requires `B86_BUDGET` and compares the resulting CS, IP, general/segment registers and defined FLAGS against the authoritative interpreter step. If a comparison differs, further JIT validation is disabled. The JIT state is never committed.

Install: extract ZIP into `C:\blitzBUS` (the ZIP contains `src/` at its root), replacing files.

```powershell
cd C:\blitzBUS
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180 -AutoTests
```

Do not use `-NoBuild` or `-NoFlash`. Hardware tests are not yet run.
