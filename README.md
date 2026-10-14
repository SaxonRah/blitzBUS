# blitzBUS DOS 6.22 boot diagnostic — inline-comment anchor fix

## What actually failed

The previous script matched the entire `C.model = BB_CPU_MODEL;` line, requiring an immediate LF/CRLF. The real blitzBUS source has a trailing inline comment:

```c
    C.model = BB_CPU_MODEL;            /* v63: 0 = 8086 (exact), 1 = 80186 instruction set */
```

That explains why even the mixed-EOL self-tests passed but `probe` found zero matching lines. This revision matches one C statement with optional trailing whitespace or C comments, preserves the original full line, and reports nearby source lines if an anchor differs again.

## Install

Extract the archive directly to `C:\blitzBUS`, **overwriting only** `bb_dos622_boot_diag_v1.py`. The diagnostic C source itself is not premodified by the ZIP.

```powershell
cd C:\blitzBUS
python -m py_compile .\bb_dos622_boot_diag_v1.py
python .\bb_dos622_boot_diag_v1.py selftest
python .\bb_dos622_boot_diag_v1.py probe
python .\bb_dos622_boot_diag_v1.py apply
python .\bb_dos622_boot_diag_v1.py verify
python .\bb_dos622_ipl_v1.py verify
```

Do **not** run `apply` if `probe` fails, and do not edit the IPL manifest manually. A failed probe/compile from the previous version wrote nothing. `verify` requires a successful `apply`; a missing state directory before that is expected.

Rebuild and run using your existing `bb_live_run.ps1` with `BB_CPU=286`, `BB_CODE_KB=232`, and the existing stable JIT settings. Look for `[bb622-diag] 01` through `16` at startup. These identify whether the failure occurs in CPU init, 386 probe, JIT setup, SD sector reading, or the boot handoff. Send the next boot log.

## Protection

- No change to the 286 Thumb-2 translator, native code cache, or SD clock fix.
- The installer checks SHA-256 hashes against the existing IPL state before modifying two source files.
- Updated parent IPL hashes permit the existing IPL `verify` command to work.
- `restore` reverts this diagnostic layer byte-for-byte. Do not restore other layers out of order.
- Host tests cover LF, CRLF, mixed EOLs, actual inline C comments, manifests, and exact restoration; RP2350 hardware execution remains unverified.
