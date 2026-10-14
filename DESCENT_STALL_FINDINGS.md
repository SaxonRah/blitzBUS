# Descent installer stall — analysis of actual RP2350 capture

Source capture: `bb-live-20261014-174310-console.txt` (746 lines). These are observations of this capture and the current publicly available `SaxonRah/blitzBUS` source, **not** evidence that a proposed PIC change has been tested on the RP2350.

## Confirmed

- Cold C: boot succeeded and DOS 6.22 ran.
- Descent installer read `DESCENT1.IMG` via B: and wrote the first ~1.4 MiB data file onto C:.
- After disk1, 18 consecutive 5s samples (#18..#35) repeatedly hit segment `0FF2`, especially `0FF2:87A2..87C2`. No subsequent B: disk #2 mount or read occurs in this log.
- Each late sample retires approximately 13.6 million instructions, but `bios13=451`, `other=180631`, `ivt=180364` stop increasing.
- All last 10 samples have `FLAGS=0093`, so IF=0 at each sampled location. This is not proof IF is permanently disabled at *every* instruction: for example the code at 87C2 starts with `STI` (`FB`).
- Reconstructed instructions show I/O `out 43h` (PIT counter latch), `in 40h` (PIT channel 0), and `in 20h` (PIC command). The firmware logged PIT counter bytes changing across successive iterations.
- DOS6 logs `IRQ0 delivery SUPPRESSED`. In source `src/bb_live.c`, the DOS6 branch skips `bb_irq36_dispatch()` entirely, and the only timer edge scheduler `bb_irq36_schedule()` is invoked *inside* that dispatcher. BIOS clock tick memory at BDA `0040:006C` advances separately through `bb_v25_bios_time()`.

## Strong hypothesis

The installer is polling the PIT/PIC timer path, and the PIC isn't seeing IRQ0 edges because the DOS6 suppression blocks **both IRQ0 delivery and IRQ0 edge scheduling**. This could explain an endless busy-wait even while PIT register reads and guest instruction counts change.

## Not proven

- That IRQ0 is definitely the awaited PIC input, or which PIC IRR/ISR mode this program selected.
- That enabling IRQ0 delivery fixes the stall; the old guest-stack failure is still a risk.
- That no separate CPU/flags bug occurs inside the loop.

## Minimal controlled next experiment

1. Add **rate-limited, read-only** tracing of PIC ports `20h/21h` and PIT channel 0, including IMR/IRR/ISR, PIC read mode, reload count, and IF at the same polling site.
2. Keep actual guest IRQ injection disabled. In a controlled A/B build, call only `bb_irq36_schedule()` for DOS6 so the PIC can latch timer edges, without `bb_irq36_dispatch()` pushing onto the guest stack. Compare stall address, PIC `IRR`, BIOS counters, and screen progression with baseline.
3. If the non-injecting scheduler experiment fixes the polling loop, proceed to proper IRQ0 delivery separately with explicit stack/IRET validation, avoiding double-advancing the BIOS tick (which already increments externally).
4. Preserve `DOS622_HDD.IMG` prior to running installation tests.

The new `bb622_logview.py` runs in another window and **does not change firmware**. It gives the developer permanent, copyable diagnostic output instead of repainting the DOS screen.
