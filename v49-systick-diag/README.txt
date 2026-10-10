v49 SysTick diagnostic (not a JIT optimization)

Only replaces blitzBUS/src/bb_v49_pc.h; backs up old version.

python .\v49-systick-diag\install_v49_diag.py --blitzbus C:\blitzBUS --check
python .\v49-systick-diag\install_v49_diag.py --blitzbus C:\blitzBUS --apply

Run your usual bb_live_run.ps1 command. Look for:
[bb-v49-systick-diag] ctrl=... load=... val=... icsr=... vtor=... vector=... expected=... enabled=... seq=...

To restore ONLY the diagnostic header:
python .\v49-systick-diag\install_v49_diag.py --blitzbus C:\blitzBUS --restore

No change to blitz86 code, the SysTick ISR, or DOS PIC/PIT.
SysTick CTRL reading resets the COUNTFLAG bit, but this only happens on report.
