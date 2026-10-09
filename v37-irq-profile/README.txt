blitzBUS v37 — IRQ timing instrumentation (no IRQ delivery logic or JIT changes)

Install over working v36:
  python .\v37-irq-profile\install_v37_irq_profile.py C:\blitzBUS --check
  python .\v37-irq-profile\install_v37_irq_profile.py C:\blitzBUS --apply

Build/flash as usual via scripts\bb_live_run.ps1. Run 3DBENCH v1.0 and capture results.
The existing Ctrl+] report output will gain [bb-v37-irq-profile] lines.

Measurements:
  polls: number of PIC scheduler checks
  sampled: every 128th check (host clock probes add minor overhead)
  poll-us-sum / sampled: average sampled dispatch duration INCLUSIVE of clock instrumentation
  eoi-us-sum / eoi-samples: mean wall-time from INT08 dispatch to PIC EOI
  outstanding: delivered INT08 awaiting PIC EOI
  hist-us: coarse IRQ service-latency histogram; includes guest instruction time,
           dispatch pauses, and host scheduling. NOT pure IRQ CPU time.

WARNING: EOI measurements and poll sampling perturb benchmark slightly. Compare
functional behavior first; restore v36 for official FPS measurements.

Restore v36:
  python .\v37-irq-profile\install_v37_irq_profile.py C:\blitzBUS --restore

Host test (if C compiler available):
  gcc -std=c11 -O2 -I src test_irq_v37.c -o test_irq_v37 && ./test_irq_v37
