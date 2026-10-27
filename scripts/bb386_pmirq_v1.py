#!/usr/bin/env python3
"""BB386_PMIRQ_V1: deliver PIT IRQ0 while the 386 is in protected mode.

Needs blitz86 r67 (b86_irq) and BB386_PMSLICE_V1. Real-mode IRQ0 delivery
for DOS 6.22 stays exactly as it was (suppressed); this only acts while
CR0.PE=1. At every slice boundary, and between the protected-mode slice
re-entries, the v36 PIC/PIT model is advanced; a pending, unmasked IRQ0
that is not already in service is delivered through the guest IDT with
b86_irq() (interrupt/trap gate or task gate). DOS/4GW then runs its own
handler, reflects to the real-mode INT 08h chain or to the program's
protected-mode handler, and EOIs through port 20h as on a PC.

Build with -DBB386_PM_IRQ0=0 to disable.
Usage: python .\\scripts\\bb386_pmirq_v1.py  (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_live.c")
MARK = "BB386_PMIRQ_V1"
EDITS = [
("helper (before bb386_pm_track)",
"static void bb386_pm_track(int rc)\n",
"""/* BB386_PMIRQ_V1: PIT IRQ0 through the guest IDT while CR0.PE=1. */
#ifndef BB386_PM_IRQ0
#define BB386_PM_IRQ0 1
#endif
static unsigned long bb386_pmirq_delivered, bb386_pmirq_blocked;
static void bb386_pmirq_poll(void)
{
    if (!BB386_PM_IRQ0 || C.model < B86_CPU_386 || !(C.msw & 1u)) return;
    bb_irq36_schedule(bb_now_us());
    if (!(bb_irq36.irr & 1u) || (bb_irq36.imr & 1u) || (bb_irq36.isr & 1u)) return;
    if (!b86_irq(&C, bb_irq36.base)) { ++bb386_pmirq_blocked; return; }   /* IF=0 or mid-transition */
    bb_irq36.irr &= (uint8_t)~1u;
    if (!bb_irq36.auto_eoi) bb_irq36.isr |= 1u;
    bb_irq36.delivered++;
    ++bb386_pmirq_delivered;
    if (bb386_pmirq_delivered <= 4u || (bb386_pmirq_delivered & (bb386_pmirq_delivered - 1u)) == 0u) {
        printf("[bb386-irq] IRQ0 #%lu -> INT %02X in protected mode at %04X:%08lX pit-reload=%u (%lu Hz) blocked=%lu edges=%llu coalesced=%llu\\n",
               bb386_pmirq_delivered, (unsigned)bb_irq36.base, (unsigned)(uint16_t)C.seg[B86_CS],
               (unsigned long)C.ip, (unsigned)(bb_pit.c[0].reload_raw ? bb_pit.c[0].reload_raw : 65536u),
               (unsigned long)(1193182u / (bb_pit.c[0].reload_raw ? bb_pit.c[0].reload_raw : 65536u)),
               bb386_pmirq_blocked, (unsigned long long)bb_irq36.edges, (unsigned long long)bb_irq36.coalesced);
        fflush(stdout);
    }
}

static void bb386_pm_track(int rc)
"""),
("slice start",
"        rc=b86_jit_run(&C, bb_v10_budget);\n    /* BB386_PMSLICE_V1",
"        rc=(bb386_pmirq_poll(), b86_jit_run(&C, bb_v10_budget));   /* BB386_PMIRQ_V1 */\n    /* BB386_PMSLICE_V1"),
("slice re-entry",
"            C.irq = 0u;\n            rc = b86_jit_run(&C, bb_v10_budget);\n",
"            C.irq = 0u;\n            bb386_pmirq_poll();                                   /* BB386_PMIRQ_V1 */\n            rc = b86_jit_run(&C, bb_v10_budget);\n"),
]
def main():
    s = open(PATH, newline="").read()
    if MARK in s:
        print("already applied"); return 0
    if "BB386_PMSLICE_V1" not in s:
        print("ABORT: apply scripts\\bb386_pmslice_v1.py first"); return 1
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    for name, old, new in EDITS:
        if s.count(old) != 1:
            print(f"ABORT: anchor '{name}' found {s.count(old)} times; bb_live.c unchanged"); return 1
    for name, old, new in EDITS: s = s.replace(old, new, 1)
    bak = PATH + ".pre_pmirq_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(open(PATH, newline="").read())
    if crlf: s = s.replace("\n", "\r\n")
    open(PATH, "w", newline="").write(s)
    print("BB386_PMIRQ_V1 applied to", PATH); return 0
if __name__ == "__main__":
    sys.exit(main())
