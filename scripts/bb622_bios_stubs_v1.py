#!/usr/bin/env python3
"""BB622_BIOS_STUBS_V1: give the firmware vectors real ROM entry points.

blitzBUS services BIOS INT 10h-17h and 1Ah for every INT instruction, but left
their IVT entries 0000:0000. Software that *chains* to a BIOS vector with
PUSHF; CALL FAR [saved vector] instead of INT jumps to 0000:0000 and runs the
interrupt table as code. DOS/4GW does exactly that at startup: INT 21h/35h
for vector 15h, then PUSHF; CALL FAR CS:[12C4] with AX=BF01 (DOS/16M probe)
from 1231:6570 -- the halt the V14/V15 diagnostics caught. Reproduced on the
host with blitz86 tests/dos4gw_host.c --pico-ivt.

This seeds F000:0140 + 8*(v-10h) with "INT v; RETF 2" for every serviced
vector whose IVT entry is still null at boot (before DOS captures its
originals). The INT inside the stub reaches the same blitzBUS service; RETF 2
returns to the far caller and keeps the result flags (standard BIOS style).
INT-instruction callers are unaffected. Never overwrites a valid vector or
occupied ROM bytes.

Usage: python .\\scripts\\bb622_bios_stubs_v1.py   (then rebuild)
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_dos622_bios.inc")
MARK = "BB622_BIOS_STUBS_V1"

FUNC_ANCHOR = "static bool BB622_FLASH bb622_boot_floppy(MdRuntime *rt)\n"
FUNC = r'''/* BB622_BIOS_STUBS_V1: ROM entry points for the serviced BIOS vectors so
 * PUSHF; CALL FAR [vector] chaining (DOS/4GW INT 15h BF01 probe) works. */
static void BB622_FLASH bb622_bios_stubs_seed(MdRuntime *rt)
{
    MdX86 *c = &rt->cpu;
    static const uint8_t vecs[] = { 0x10u,0x11u,0x12u,0x13u,0x14u,0x15u,0x16u,0x17u,0x1Au };
    const uint16_t seg = 0xF000u;
    unsigned seeded = 0u, i, k;
    for (i = 0u; i < sizeof vecs; ++i) {
        const uint8_t v = vecs[i];
        const uint16_t off = (uint16_t)(0x0140u + 8u * (uint16_t)(v - 0x10u));
        const uint8_t stub[5] = { 0xCDu, v, 0xCAu, 0x02u, 0x00u };   /* int v; retf 2 */
        if (md_x86_read16(c, 0u, (uint16_t)(v * 4u)) | md_x86_read16(c, 0u, (uint16_t)(v * 4u + 2u)))
            continue;                                   /* never replace a valid vector */
        for (k = 0u; k < sizeof stub; ++k) {
            uint8_t b = md_x86_read8(c, seg, (uint16_t)(off + k));
            if (b != 0u && b != stub[k]) break;
        }
        if (k != sizeof stub) continue;                 /* ROM bytes occupied */
        for (k = 0u; k < sizeof stub; ++k) md_x86_write8(c, seg, (uint16_t)(off + k), stub[k]);
        md_x86_write16(c, 0u, (uint16_t)(v * 4u), off);
        md_x86_write16(c, 0u, (uint16_t)(v * 4u + 2u), seg);
        md_runtime_mark_code_range(rt, seg, off, (uint32_t)sizeof stub);
        ++seeded;
    }
    printf("[bb622-biosstub] %u BIOS vectors -> F000:0140.. (INT v; RETF 2) for far-call chaining\n", seeded);
    fflush(stdout);
}

'''
CALL_OLD = "    bb622_bios_irqchain_seed(rt); /* BB622_BIOS_IRQCHAIN_V1: seed before DOS captures old INT08 */\n"
CALL_NEW = CALL_OLD + "    bb622_bios_stubs_seed(rt);    /* BB622_BIOS_STUBS_V1: before DOS captures original vectors */\n"

def main():
    s = open(PATH, newline="").read()
    if MARK in s:
        print("already applied"); return 0
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    for name, a in (("boot_floppy", FUNC_ANCHOR), ("irqchain call", CALL_OLD)):
        if s.count(a) != 1:
            print(f"ABORT: anchor {name} found {s.count(a)} times; file unchanged"); return 1
    s = s.replace(FUNC_ANCHOR, FUNC + FUNC_ANCHOR, 1).replace(CALL_OLD, CALL_NEW, 1)
    bak = PATH + ".pre_bios_stubs_v1"
    if not os.path.exists(bak):
        open(bak, "w", newline="").write(open(PATH, newline="").read())
    if crlf: s = s.replace("\n", "\r\n")
    open(PATH, "w", newline="").write(s)
    print("BB622_BIOS_STUBS_V1 applied to", PATH)
    return 0

if __name__ == "__main__":
    sys.exit(main())
