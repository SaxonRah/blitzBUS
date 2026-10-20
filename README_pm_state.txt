BB386_PM_STATE_V1 (extract over C:\, then run once, then rebuild):

    python .\scripts\bb386_pm_state_v1.py

Patches src\bb_live.c in place (backup: bb_live.c.pre_pm_state_v1):
* to_b86(): while PE=1 nothing is copied back from microDOS's 16-bit view
  (was: EIP truncated to 16 bits and CS/SS/DS/ES reloaded as real-mode
  segments at every slice). Real mode keeps BB386_GPR_HIGH_V1 as is.
* Targets the chore/blitzbus-repo-cleanup bb_live.c (commit ad3bad6).
* Between-slice IRQ delivery (real-mode IVT) and the BIOS-segment hand-off
  are skipped while PE=1.
* v17 "first invalid boundary" check is skipped while PE=1.
* A slice that retires 0 instructions in protected mode (or a 386 shutdown)
  stops with a [bb386-pm] STOP dump instead of falling back to microDOS's
  8086 interpreter.
* Log lines: [bb386-pm] ENTER / LEAVE, progress at slices 2,4,8,16...
If an anchor is missing the script aborts and leaves bb_live.c untouched.
