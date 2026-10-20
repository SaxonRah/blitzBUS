BB386_PM_STATE_V1 (extract over C:\, then run once, then rebuild):

    python .\scripts\bb386_pm_state_v1.py

Patches src\bb_live.c in place (backup: bb_live.c.pre_pm_state_v1):
* to_b86(): 386 real mode keeps the upper halves of EAX..EDI; protected mode
  copies nothing back from microDOS's 16-bit view (was: upper halves of all
  GPRs and EIP zeroed, CS/SS/DS/ES reloaded as real-mode segments at every
  slice and after every hooked BIOS INT).
* Between-slice IRQ delivery (real-mode IVT) and the BIOS-segment hand-off
  are skipped while PE=1.
* v17 "first invalid boundary" check is skipped while PE=1.
* A slice that retires 0 instructions in protected mode (or a 386 shutdown)
  stops with a [bb386-pm] STOP dump instead of falling back to microDOS's
  8086 interpreter.
* Log lines: [bb386-pm] ENTER / LEAVE, progress at slices 2,4,8,16...
If an anchor is missing the script aborts and leaves bb_live.c untouched.
