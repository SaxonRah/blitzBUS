# blitzBUS SWD fault catch

Halts the core on HardFault entry (DEMCR.VC_HARDERR) and dumps registers, fault
status registers, the exception frame and code bytes around the stacked PC.

1. Start OpenOCD as in `blitz_swd_v2/README.md`.
2. `python .\blitz_swd_faultcatch\swd_faultcatch.py --out .\logs\faultcatch.txt`
3. Run 3DBENCH. To test the reflash hypothesis directly, run
   `picotool reboot -f -u` while 3DBENCH is running.

If nothing halts during long benchmark runs but one appears on the forced
reboot, the fault is in the BOOTSEL transition, not in blitz86.
