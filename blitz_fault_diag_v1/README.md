# blitzBUS v50 fault diagnostics — full file package

Full replacement `src/bb_live.c` built from the captured `memfast_source_snapshot.zip` source. This adds **boot-time reporting only**, not a new interrupt handler. The existing handler already captures core registers in a 16-word no-init buffer and resets with the watchdog.

The v50 report adds: full stacked register print, EXC_RETURN, HFSR status flags, CFSR valid bits, guest-last-sync CS:IP, and classification of the stacked PC against the JIT allocation. The guest CS:IP is the last synchronized location, **not necessarily the instruction actually executing at the fault**. Fault-address registers are not necessarily meaningful unless their validity flags are set.

## Safety

The installer compares SHA-256 against the captured source and refuses to overwrite newer/different `bb_live.c`. If it refuses, provide your actual `C:\blitzBUS\src\bb_live.c` rather than forcing this historical replacement.

Expected input SHA-256: `4e654e4712cb3d4ed29c086b52f2a491d2a782d735baa32f73ebef56f9210735`

Output SHA-256: `ff4886d44c5353992ba63729b6ea69d35f6bb28e06d582cbf8b06c0d7d450855`

## Windows PowerShell

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\blitz_fault_diag_v1.zip" C:\blitzBUS -Force
.\blitz_fault_diag_v1\install.ps1 -Mode Check
.\blitz_fault_diag_v1\install.ps1 -Mode Install
```

Then run your existing `bb_live_run.ps1` workflow. The diagnostic prints on the **boot following a fault**. A clean run may print nothing; this is expected. Source changes to `bb_live.c` require recompilation. `analyze_fault_logs.ps1` is read-only and works even without installation.

Rollback: `.\blitz_fault_diag_v1\install.ps1 -Mode Restore`.

No JIT optimizations are changed. Keep `B86_OPT_CS_CONST=0`, `B86_OPT_PAGE_ZERO=1`, `B86_EA_IMM12_FAST=1` during this diagnostic.

## Limitations

No code-cache bytes are preserved across reboot; a further SWD/code snapshot will be required to disassemble the exact instruction. A nested fault before the watchdog reboot may prevent diagnostics from being saved. The original 16-word fault record is preserved unchanged.
