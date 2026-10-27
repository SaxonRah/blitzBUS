#!/usr/bin/env python3
"""BB386_PM_STATE_V1: patch C:\\blitzBUS\\src\\bb_live.c in place.

Fixes three ways blitzBUS corrupted a 386 guest between slices:
  1. to_b86() copied microDOS's 16-bit CS:IP, segments and flags back into
     blitz86 at every slice, truncating EIP to 16 bits and reloading
     CS/SS/DS/ES as real-mode segments even in protected mode. Now nothing
     comes back from microDOS's stale 16-bit view while PE=1 (the existing
     BB386_GPR_HIGH_V1 real-mode behaviour is unchanged).
  2. The between-slice IRQ dispatcher delivered interrupts through the
     real-mode IVT using microDOS's copy of CS:IP/SS:SP. Skipped while PE=1.
  3. A slice that retired 0 instructions fell back to microDOS's 8086
     interpreter. In protected mode that is always wrong: it now stops with
     a full 386 register/descriptor dump ([bb386-pm] STOP ...).
The v17 "first invalid boundary" diagnostic (real-mode CS*16+IP test) is
skipped in protected mode. Also logs protected-mode entry/exit and PM progress at power-of-two slices.

Usage:  python .\\scripts\\bb386_pm_state_v1.py   (then rebuild as usual)
Leaves bb_live.c.pre_pm_state_v1 as a backup. Safe to run twice.
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_live.c")
MARK = "BB386_PM_STATE_V1"

TO_B86_OLD = """B86_HOT static void to_b86(void)
{
    MdX86 *m = &R->cpu;
    /* BB386_GPR_HIGH_V1: retain 386 high halves across MdX86 slice handoff. */
"""
TO_B86_NEW = """B86_HOT static void to_b86(void)
{
    MdX86 *m = &R->cpu;
    /* BB386_PM_STATE_V1: in protected mode microDOS's CS:IP, segments and
       flags are a stale 16-bit view of selectors and a 32-bit EIP (copying
       them back truncated EIP to 16 bits every slice), so nothing comes back. */
    if (C.model >= B86_CPU_386 && (C.msw & 1u)) return;
    /* BB386_GPR_HIGH_V1: retain 386 high halves across MdX86 slice handoff. */
"""

TRY_OLD = "B86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)\n{\n"
TRY_NEW = r'''/* BB386_PM_STATE_V1: protected-mode bookkeeping and the stop dump. */
static inline int bb386_pm(void) { return C.model >= B86_CPU_386 && (C.msw & 1u) != 0; }
static unsigned long bb386_pm_slices;
static int bb386_pm_was;
static const char *bb386_rc_name(int rc)
{
    switch (rc) {
    case B86_OK: return "ok"; case B86_HALT: return "halt"; case B86_EXIT: return "exit";
    case B86_BUDGET: return "budget"; case B86_TRAP: return "trap";
    case B86_UNSUPPORTED: return "unsupported"; case B86_SHUTDOWN: return "shutdown";
    default: return "?";
    }
}
static uint32_t bb386_cs_linear(void)
{
    if (C.msw & 1u) return C.pm386.seg[B86_CS].base + C.ip;
    return ((uint32_t)(uint16_t)C.seg[B86_CS] << 4) + (C.ip & 0xFFFFu);
}
static void bb386_pm_regs(const char *tag)
{
    const B86PM1Cache *s = C.pm386.seg;
    printf("[bb386-pm] %s cr0=%04X cs=%04X eip=%08lX cs.base=%08lX cs.limit=%08lX cs.acc=%02X cs.flg=%02X\n",
           tag, (unsigned)C.msw, (unsigned)s[B86_CS].selector, (unsigned long)C.ip,
           (unsigned long)s[B86_CS].base, (unsigned long)s[B86_CS].limit,
           (unsigned)s[B86_CS].access, (unsigned)s[B86_CS].flags);
    printf("[bb386-pm]   eax=%08lX ebx=%08lX ecx=%08lX edx=%08lX esi=%08lX edi=%08lX ebp=%08lX esp=%08lX flags=%04X\n",
           (unsigned long)C.r[B86_AX], (unsigned long)C.r[B86_BX], (unsigned long)C.r[B86_CX],
           (unsigned long)C.r[B86_DX], (unsigned long)C.r[B86_SI], (unsigned long)C.r[B86_DI],
           (unsigned long)C.r[B86_BP], (unsigned long)C.r[B86_SP], (unsigned)b86_get_flags(&C));
    printf("[bb386-pm]   ss=%04X/%08lX ds=%04X/%08lX es=%04X/%08lX fs=%04X/%08lX gs=%04X/%08lX gdt=%08lX idt=%08lX\n",
           (unsigned)s[B86_SS].selector, (unsigned long)s[B86_SS].base,
           (unsigned)s[B86_DS].selector, (unsigned long)s[B86_DS].base,
           (unsigned)s[B86_ES].selector, (unsigned long)s[B86_ES].base,
           (unsigned)s[B86_FS].selector, (unsigned long)s[B86_FS].base,
           (unsigned)s[B86_GS].selector, (unsigned long)s[B86_GS].base,
           (unsigned long)C.gdt_base, (unsigned long)C.idt_base);
    uint32_t lin = bb386_cs_linear();
    printf("[bb386-pm]   code@%08lX:", (unsigned long)lin);
    for (uint32_t j = 0; j < 16u; ++j) {
        if (lin + j < B86_RAM_BYTES) printf(" %02X", (unsigned)*b86_host(&C, lin + j));
        else printf(" ??");
    }
    printf("\n");
    fflush(stdout);
}
static void bb386_pm_track(int rc)
{
    const int pm = bb386_pm();
    if (pm && !bb386_pm_was) {
        printf("[bb386-pm] ENTER protected mode (rc=%s retired=%lu)\n", bb386_rc_name(rc), (unsigned long)C.icnt);
        bb386_pm_regs("enter");
    } else if (!pm && bb386_pm_was) {
        printf("[bb386-pm] LEAVE protected mode -> real mode %04X:%04X after %lu PM slices\n",
               (unsigned)C.seg[B86_CS], (unsigned)(C.ip & 0xFFFFu), bb386_pm_slices);
        fflush(stdout);
    }
    bb386_pm_was = pm;
    if (pm) {
        ++bb386_pm_slices;
        if ((bb386_pm_slices & (bb386_pm_slices - 1u)) == 0u && bb386_pm_slices >= 2u) {
            char tag[40];
            snprintf(tag, sizeof tag, "slice=%lu rc=%s", bb386_pm_slices, bb386_rc_name(rc));
            bb386_pm_regs(tag);
        }
    }
}
static void bb386_pm_stop(MdRuntime *rt, int rc)
{
    char tag[48];
    snprintf(tag, sizeof tag, "STOP rc=%s retired=0", bb386_rc_name(rc));
    printf("\n");
    bb386_pm_regs(tag);
    printf("[bb386-pm] blitz86 made no progress; the 8086 fallback interpreter is not used for 386 %s\n",
           (C.msw & 1u) ? "protected mode" : "shutdown");
    fflush(stdout);
    rt->fault_linear = bb386_cs_linear();
    rt->fault_opcode = rt->fault_linear < B86_RAM_BYTES ? *b86_host(&C, rt->fault_linear) : 0u;
    rt->stop_reason = MD_STOP_FAULT;
}

B86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)
{
'''

IRQ_OLD = """    /* BB_DOS622_IRQ0_ISOLATION_V1: A/B test native IRQ0 guest-stack delivery */
    if (rt == R) {"""
IRQ_NEW = """    /* BB_DOS622_IRQ0_ISOLATION_V1: A/B test native IRQ0 guest-stack delivery */
    /* BB386_PM_STATE_V1: real-mode IVT delivery is wrong while PE=1. */
    if (rt == R && !bb386_pm()) {"""

BIOS_OLD = "    if (rt != R || rt->cpu.cs == bios_seg) {"
BIOS_NEW = "    if (rt != R || (rt->cpu.cs == bios_seg && !bb386_pm())) {   /* BB386_PM_STATE_V1 */"

V17_OLD = '    if (bb_v17_guard(rt,"jit-exit",v13_before_cs,v13_before_ip,'
V17_NEW = '    if (!bb386_pm() && bb_v17_guard(rt,"jit-exit",v13_before_cs,v13_before_ip,   /* BB386_PM_STATE_V1 */'

RET_OLD = "    return C.icnt != 0 || rc == B86_HALT || rt->stop_reason != MD_STOP_NONE;\n}"
RET_NEW = """    /* BB386_PM_STATE_V1: never hand a 386 protected-mode (or shut-down)
       CPU to microDOS's 8086 interpreter. */
    bb386_pm_track(rc);
    if (C.model >= B86_CPU_386 && C.icnt == 0u && rc != B86_HALT &&
        rt->stop_reason == MD_STOP_NONE && ((C.msw & 1u) || rc == B86_SHUTDOWN)) {
        if (rc == B86_EXIT || rc == B86_BUDGET) return 1;      /* retry next slice */
        bb386_pm_stop(rt, rc);
        return 1;
    }
    return C.icnt != 0 || rc == B86_HALT || rt->stop_reason != MD_STOP_NONE;
}"""

def main():
    s = open(PATH, newline="").read()
    if MARK in s:
        print("bb_live.c already has BB386_PM_STATE_V1; nothing to do")
        return 0
    crlf = "\r\n" in s
    if crlf:
        s = s.replace("\r\n", "\n")
    for name, old in (("to_b86", TO_B86_OLD), ("bb_live_try", TRY_OLD),
                      ("IRQ block", IRQ_OLD), ("BIOS-segment test", BIOS_OLD),
                      ("slice return", RET_OLD), ("v17 guard", V17_OLD)):
        n = s.count(old)
        if n != 1:
            print(f"ABORT: anchor '{name}' found {n} times (expected 1); bb_live.c unchanged")
            return 1
    s = (s.replace(TO_B86_OLD, TO_B86_NEW, 1).replace(TRY_OLD, TRY_NEW, 1)
          .replace(IRQ_OLD, IRQ_NEW, 1).replace(BIOS_OLD, BIOS_NEW, 1)
          .replace(RET_OLD, RET_NEW, 1).replace(V17_OLD, V17_NEW, 1))
    backup = PATH + ".pre_pm_state_v1"
    if not os.path.exists(backup):
        with open(backup, "w", newline="") as f:
            f.write(open(PATH, newline="").read())
    if crlf:
        s = s.replace("\n", "\r\n")
    with open(PATH, "w", newline="") as f:
        f.write(s)
    print("BB386_PM_STATE_V1 applied to", PATH)
    print("backup:", backup)
    return 0

if __name__ == "__main__":
    sys.exit(main())
