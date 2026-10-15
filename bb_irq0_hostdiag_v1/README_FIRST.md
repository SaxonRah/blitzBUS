# blitzBUS IRQ0 host regression — V1

The October 14 one-shot raw log was not found on C:, and the retained October 13 log contains no IRQ0 trial. **Do not re-arm Ctrl+U yet.**

This package does not change any tracked blitzBUS or microDOS source, and it does not contact the Pico, format/copy disks, or use COM5. It compiles a separate hosted C test linked against your existing `C:\microDOS\build-host\Release\microdos_runtime.lib`.

## Install and run

Extract the ZIP to `C:\blitzBUS` (its `bb_irq0_hostdiag_v1` folder is included). Then:

```powershell
cd C:\blitzBUS
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bb_irq0_hostdiag_v1\run_host.ps1
```

Or, if you have just rebuilt `microdos_runtime.lib` and do not want to build it again:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bb_irq0_hostdiag_v1\run_host.ps1 -NoBuild
```

The helper uses VS 2022 x64 and creates only `bb_irq0_hostdiag_v1\build-host` outputs. It reuses the microDOS host runtime library. It does NOT test the RP2350 firmware build.

## Test coverage

1. Canonical `md_runtime_interrupt()` real-mode INT08 frame vs the same guest-stack push order found in the current `src/bb_irq.h` IRQ0 dispatcher. This is a *copy of the relevant sequence*, not a binary test of the compiled `bb_irq36_dispatch()` routine.
2. Inspect 16-bit IP, CS and FLAGS on SS:SP, and ensure IF and TF clear on entry.
3. Execute the real `md_interp_step()` IRET instruction in the microDOS host library; verify FLAGS and CS:IP and SP are restored.
4. Repeat with SP crossing the 16-bit offset wrap boundary.
5. Corruption control: deliberately zero saved IP and CS, verifying that the same IRET *can* lead to `0000:0000`. This illustrates one candidate explanation only.

## Important limits

- Passing this test only proves the **microDOS host INT entry/interpreter IRET** and the copied PIC entry sequence. It **cannot** prove that blitz86 JIT executes the real DOS IRQ08 handler, honors its instructions, or returns with the right frame.
- A pass is **not permission** to re-arm guest IRQ0. The next test is a blitz86 guest-handler execution differential with a bounded trace and no SD writes.
- The historical IRQ0 event `0E2A:003C -> 0000:0000` cannot be reconstructed from a nonexistent log.
- If compilation fails, send the entire error output. Do not change microDOS source to make this one diagnostic compile.
