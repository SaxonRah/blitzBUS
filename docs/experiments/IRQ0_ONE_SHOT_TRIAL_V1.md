# blitzBUS DOS 6.22 — IRQ0 one-shot experiment V1

This is a **bounded diagnostic experiment**, not a proven fix. In the same-run PIC test, Descent read IRR=01 (IRQ0 pending) and remained at `0FF2:87A2–87C2`; the scheduler advanced and **delivered=0**. Next we must distinguish a missing guest IRQ service from an emulator inability to observe IF-enabled instruction boundaries.

**Prerequisites:** Existing `BB622_PIC_PENDING_V1` firmware source applied and verified, and `BB622_PIC_HOST_CONTROL_V1` host controls applied and verified. Existing host runner `scripts/bb_live_run_dos622_pic_control.ps1` must match its install manifest. Keep your working C: hard-disk image and all floppy images untouched. Back up `DOS622_HDD.IMG` before reattempting the Descent installer, since Descent writes to C:.

**Safety:** The firmware *does not* enable IRQ0 during DOS startup. The user explicitly arms Ctrl+U through a second-window command. It attempts **at most one legitimate guest IRQ0** using the existing PIC dispatcher, observing its normal IF/IMR/ISR/IVT eligibility checks; after that delivery it automatically switches OFF. If no delivery happens in 8 seconds, it automatically switches OFF and reports why. The experiment does **not** force interrupts while IF=0 and does not bypass the interrupt gate; it cannot guarantee the old interrupt-stability problem won't recur if the first interrupt actually executes. A reboot clears the trial state. This layer does not enable repeated timer interrupts or implement STI instruction-boundary handling.

## 1. Extract, test, probe, apply

Extract the *top-level* Python file plus its five imported dependency scripts into `C:\blitzBUS`. **Do not overwrite your existing dependencies if they differ:** the ZIP contains reference copies for standalone self-tests; use your already-installed originals. Run:

```powershell
cd C:\blitzBUS
python .\bb622_pic_pending_v1.py verify
python .\bb622_pic_host_control_v1.py verify
python .\bb622_irq0_trial_v1.py selftest
python .\bb622_irq0_trial_v1.py probe
```

If `probe` passes and you have backed up your HDD image:

```powershell
python .\bb622_irq0_trial_v1.py apply
python .\bb622_irq0_trial_v1.py verify
python .\bb622_lineage_verify_v13.py verify
```

The Python installer updates the checked source and installed current-SHA metadata as a *new*, independently reversible stage. Old original hashes and backup copies are not changed. The new host runner is cloned from the verified current PIC-control host runner; existing Ctrl+Y and Alt+G controls remain.

## 2. Rebuild and flash *once*

Use the same environment variables you already use, then:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
    .\scripts\bb_live_run_dos622_irqtrial.ps1 `
    -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 `
    -Port COM5 -Seconds 0 -ConsoleView Screen
```

For the initial run, **do not** specify `-NoBuild` or `-NoFlash`. If the board cannot enter BOOTSEL, use your established manual BOOTSEL method and verify the newly built image was flashed before testing. The installer should be left running; there is only one process allowed to own COM5.

## 3. Reproduce Descent's stall and arm exactly one guest IRQ0

Keep the DOS-console window open. From a separate PowerShell window run:

```powershell
cd C:\blitzBUS
powershell -NoProfile -ExecutionPolicy Bypass -File `
    .\scripts\bb622_irq0_trial.ps1 -TimeoutSeconds 15
```

Expect an actual `PICO ACK: [bb622-irqtrial] ARMED` line. The requester reads only newly appended bytes from the same raw log and demands the host `SENT` marker before accepting the Pico acknowledgement. Once armed, the firmware will log one of:

- `[bb622-irqtrial] DELIVERED one guest IRQ0; AUTO-OFF ...`
- `[bb622-irqtrial] TIMEOUT no guest IRQ0 delivered; AUTO-OFF ... if0_delta=... masked_delta=...`

If a crash or hardfault occurs while testing, leave the HDD intact and reboot into the known-good firmware. Do not repeatedly arm without inspecting the log first.

After 10 seconds, obtain a permanent report in another window:

```powershell
python .\bb622_irq0_report.py --root C:\blitzBUS
```

**Send:** The trial command's acknowledgement, `bb622_irq0_report.py` output, and any `bb-v36-irq` or hardfault lines. That identifies whether the one interrupt was delivered, not deliverable because IF or PIC mask stayed disabled, or delivered into a broken ISR path.

## 4. Roll back this new layer

Stop the runner. While the source SHA still matches the installed state:

```powershell
python .\bb622_irq0_trial_v1.py verify
python .\bb622_irq0_trial_v1.py restore
python .\bb622_pic_pending_v1.py verify
```

Then rebuild/flash the previous firmware if you want to return to its behavior. Never remove earlier stages to roll back this one.

## Validation scope

LF and CRLF source transformations, one-delivery gate, timeout diagnostics, host request string and byte-exact rollback have passed synthetic self-tests. **No real Pico compilation or Descent continuation has been executed in this environment.** The first real IRQ0 may still cause a guest fault. Avoid claiming success until the Pico tests report `DELIVERED` *and* Descent advances safely.
