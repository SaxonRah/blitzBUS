#!/usr/bin/env python3
"""BB386_PMKBD_V1: PC keyboard (port 60h/64h + IRQ1) for protected-mode games.

Needs BB386_PMIRQ_V1 (and blitz86 r67+). DOS/4GW programs such as Descent
install their own INT 09h handler and read scancodes from port 60h, so the
BIOS keyboard buffer alone gives them no input. While a DOS/4GW program is
active (protected mode seen in the last 2 s), every key typed in the
keyboard window is also queued as a make code and a break code ~70 ms later.
Each scancode is latched into port 60h (port 64h bit 0 = output buffer
full) and IRQ1 is raised; in protected mode it is delivered through the
guest IDT with b86_irq(), after any pending IRQ0. If the real-mode INT 09h
vector is null (blitzBUS boots without a BIOS), a minimal handler that
reads port 60h and EOIs is seeded at F000:01A0 so a reflected IRQ1 is safe.
The BIOS buffer path for DOS is unchanged.

Usage: python .\\scripts\\bb386_pmkbd_v1.py   (then rebuild). Safe to run twice.
Build with -DBB386_PM_KBD=0 to disable.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_live.c")
MARK = "BB386_PMKBD_V1"
BLOCK = r'''/* BB386_PMKBD_V1: scancode queue, port 60h/64h and IRQ1 in protected mode. */
#ifndef BB386_PM_KBD
#define BB386_PM_KBD 1
#endif
static uint8_t bb386_kq[64], bb386_kq_head, bb386_kq_tail, bb386_k60, bb386_kobf;
static uint64_t bb386_kbd_pm_us, bb386_k_ready_us;
static unsigned long bb386_kbd_irqs;
static void bb386_kq_put(uint8_t v)
{
    const uint8_t next = (uint8_t)((bb386_kq_tail + 1u) & 63u);
    if (next != bb386_kq_head) { bb386_kq[bb386_kq_tail] = v; bb386_kq_tail = next; }
}
static void bb386_kbd_push(uint8_t scan)
{
    if (!BB386_PM_KBD || !scan || C.model < B86_CPU_386) return;
    if (!bb386_kbd_pm_us || bb_now_us() - bb386_kbd_pm_us > 2000000u) return;   /* DOS: BIOS buffer only */
    bb386_kq_put(scan);
    bb386_kq_put((uint8_t)(scan | 0x80u));
}
static int bb386_kbd_port_in(uint16_t port, uint8_t *v)
{
    if (!BB386_PM_KBD || !bb386_kbd_pm_us) return 0;
    if (port == 0x60u) { *v = bb386_k60; bb386_kobf = 0u; return 1; }
    if (port == 0x64u) { *v = (uint8_t)(0x1Cu | bb386_kobf); return 1; }
    return 0;
}
'''
POLL = r'''/* BB386_PMKBD_V1 */
static void bb386_kbd_poll(void)
{
    const uint64_t now = bb_now_us();
    uint8_t *m = b86_host_phys(&C, 0u);   /* IVT page (honours B86_PAGED mappings) */
    bb386_kbd_pm_us = now;
    if (!BB386_PM_KBD) return;
    if (!bb386_kobf && bb386_kq_head != bb386_kq_tail && now >= bb386_k_ready_us) {
        bb386_k60 = bb386_kq[bb386_kq_head]; bb386_kq_head = (uint8_t)((bb386_kq_head + 1u) & 63u);
        bb386_kobf = 1u; bb_irq36.irr |= 2u;
        bb386_k_ready_us = now + 70000u;                 /* make/break spacing */
    }
    if (!(bb_irq36.irr & 2u) || (bb_irq36.imr & 2u) || (bb_irq36.isr & 3u)) return;
    if ((bb_irq36.irr & 1u) && !(bb_irq36.imr & 1u)) return;   /* IRQ0 first */
    if (!(m[0x24] | m[0x25] | m[0x26] | m[0x27])) {      /* null real-mode INT 09h: seed a safe one */
        static const uint8_t stub[] = { 0x50, 0xE4, 0x60, 0xB0, 0x20, 0xE6, 0x20, 0x58, 0xCF };
        uint8_t *s = b86_host_phys(&C, 0xF01A0u);
        for (unsigned i = 0; i < sizeof stub; ++i) s[i] = stub[i];
        m[0x24] = 0xA0; m[0x25] = 0x01; m[0x26] = 0x00; m[0x27] = 0xF0;
    }
    if (!b86_irq(&C, (uint8_t)(bb_irq36.base + 1u))) return;
    bb_irq36.irr &= (uint8_t)~2u;
    if (!bb_irq36.auto_eoi) bb_irq36.isr |= 2u;
    if (++bb386_kbd_irqs <= 8u || (bb386_kbd_irqs & (bb386_kbd_irqs - 1u)) == 0u) {
        printf("[bb386-kbd] IRQ1 #%lu scancode %02X -> INT %02X in protected mode at %04X:%08lX\n",
               bb386_kbd_irqs, (unsigned)bb386_k60, (unsigned)(bb_irq36.base + 1u),
               (unsigned)(uint16_t)C.seg[B86_CS], (unsigned long)C.ip);
        fflush(stdout);
    }
}
'''
EDITS = [
("forward declaration",
"static void bb_v23_enqueue_ascii(uint8_t *m,unsigned c) {\n",
"static void bb386_kbd_push(uint8_t scan);   /* BB386_PMKBD_V1 */\nstatic void bb_v23_enqueue_ascii(uint8_t *m,unsigned c) {\n"),
("ascii keys",
"    ++bb_v23_keys;\n    printf(\"[bb-v23] KEY ascii=%02X scan=%02X queued=%lu\\n\",c,bb_v23_scan(c),(unsigned long)bb_v23_keys);\n",
"    ++bb_v23_keys;\n    bb386_kbd_push(bb_v23_scan(c));   /* BB386_PMKBD_V1 */\n    printf(\"[bb-v23] KEY ascii=%02X scan=%02X queued=%lu\\n\",c,bb_v23_scan(c),(unsigned long)bb_v23_keys);\n"),
("cursor/function keys",
"    ++bb_v23_keys;\n    if(bb622_vt_logged++<32u) {\n",
"    ++bb_v23_keys;\n    bb386_kbd_push(scan);   /* BB386_PMKBD_V1 */\n    if(bb622_vt_logged++<32u) {\n"),
("keyboard state + ports (before hook_in)",
"B86_HOT static uint8_t hook_in(B86Cpu *c, uint16_t port)\n{\n    uint8_t result;\n",
BLOCK + "B86_HOT static uint8_t hook_in(B86Cpu *c, uint16_t port)\n{\n    uint8_t result;\n    if(bb386_kbd_port_in(port,&result))return result;   /* BB386_PMKBD_V1 */\n"),
("poll (before IRQ0 poll)",
"static void bb386_pmirq_poll(void)\n{\n    if (!BB386_PM_IRQ0 || C.model < B86_CPU_386 || !(C.msw & 1u)) return;\n",
POLL + "static void bb386_pmirq_poll(void)\n{\n    if (!BB386_PM_IRQ0 || C.model < B86_CPU_386 || !(C.msw & 1u)) return;\n    bb386_kbd_poll();                                         /* BB386_PMKBD_V1 */\n"),
]
def main():
    s = open(PATH, newline="").read()
    if "bb386_kbd_poll" in s:
        print("already applied"); return 0
    if "BB386_PMIRQ_V1" not in s:
        print("ABORT: apply scripts\\bb386_pmirq_v1.py first"); return 1
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    for name, old, new in EDITS:
        if s.count(old) != 1:
            print(f"ABORT: anchor '{name}' found {s.count(old)} times; bb_live.c unchanged"); return 1
    for name, old, new in EDITS: s = s.replace(old, new, 1)
    bak = PATH + ".pre_pmkbd_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(open(PATH, newline="").read())
    if crlf: s = s.replace("\n", "\r\n")
    open(PATH, "w", newline="").write(s)
    print("BB386_PMKBD_V1 applied to", PATH); return 0
if __name__ == "__main__":
    sys.exit(main())
