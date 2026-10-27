#ifndef BB622_IRQ0_POSTDIAG_H
#define BB622_IRQ0_POSTDIAG_H
/* DOS 6.22 one-shot IRQ0 POST-ENTRY diagnostic only.
 * Included after the CPU, PIC, and runtime declarations; never changes guest
 * registers, memory, PIC/PIT, interrupts, or the default DOS6 IRQ suppression.
 */
#include <stdint.h>
static uint8_t bb622_post_active, bb622_post_samples;
static uint16_t bb622_post_cs, bb622_post_ip, bb622_post_flags, bb622_post_ss, bb622_post_sp;
static void bb622_post_dump(MdRuntime *rt, const char *where) {
    if (!rt || !rt->cpu.memory) return;
    const MdX86 *m = &rt->cpu;
    const uint16_t sp=(uint16_t)m->r[B86_SP];
    const uint32_t pc=((uint32_t)m->cs << 4) + (uint32_t)m->ip;
    const uint32_t sa=((uint32_t)m->ss << 4) + (uint32_t)sp;
    const uint8_t *p=m->memory;
    const int pc_ok=pc<=0x10fff0u;
    const int sp_ok=sa<=0x10fff0u;
    printf("[bb622-postirq] %s CS:IP=%04X:%04X SS:SP=%04X:%04X FLAGS=%04X "
           "AX=%04X BX=%04X CX=%04X DX=%04X SI=%04X DI=%04X BP=%04X "
           "IRR=%02X IMR=%02X ISR=%02X EOI=%llu ",
           where,(unsigned)m->cs,(unsigned)m->ip,(unsigned)m->ss,(unsigned)sp,
           (unsigned)md_x86_flags((MdX86 *)m),
           (unsigned)(uint16_t)m->r[B86_AX],(unsigned)(uint16_t)m->r[B86_BX],
           (unsigned)(uint16_t)m->r[B86_CX],(unsigned)(uint16_t)m->r[B86_DX],
           (unsigned)(uint16_t)m->r[B86_SI],(unsigned)(uint16_t)m->r[B86_DI],
           (unsigned)(uint16_t)m->r[B86_BP],
           (unsigned)bb_irq36.irr,(unsigned)bb_irq36.imr,(unsigned)bb_irq36.isr,
           (unsigned long long)bb_irq36.eois);
    if(pc_ok) printf("PC=%02X%02X%02X%02X%02X%02X%02X%02X ",
                  (unsigned)p[pc],(unsigned)p[pc+1],(unsigned)p[pc+2],(unsigned)p[pc+3],
                  (unsigned)p[pc+4],(unsigned)p[pc+5],(unsigned)p[pc+6],(unsigned)p[pc+7]);
    else printf("PC=OUT_OF_RANGE ");
    if(sp_ok) printf("STACK=%02X%02X%02X%02X%02X%02X%02X%02X%02X%02X%02X%02X",
                  (unsigned)p[sa],(unsigned)p[sa+1],(unsigned)p[sa+2],(unsigned)p[sa+3],
                  (unsigned)p[sa+4],(unsigned)p[sa+5],(unsigned)p[sa+6],(unsigned)p[sa+7],
                  (unsigned)p[sa+8],(unsigned)p[sa+9],(unsigned)p[sa+10],(unsigned)p[sa+11]);
    else printf("STACK=OUT_OF_RANGE");
    printf("\n"); fflush(stdout);
}
static void bb622_post_before(MdRuntime *rt) {
    bb622_post_active=0; bb622_post_samples=0;
    if(!rt) return;
    bb622_post_cs=rt->cpu.cs; bb622_post_ip=rt->cpu.ip;
    bb622_post_flags=md_x86_flags(&rt->cpu);
    bb622_post_ss=rt->cpu.ss; bb622_post_sp=(uint16_t)rt->cpu.r[B86_SP];
    bb622_post_dump(rt,"BEFORE-IRQ0");
}
static void bb622_post_accepted(MdRuntime *rt) {
    if(!rt || !rt->cpu.memory) return;
    bb622_post_active=1;
    bb622_post_dump(rt,"AFTER-IRQ0");
    const uint16_t sp=(uint16_t)rt->cpu.r[B86_SP];
    const uint32_t a=((uint32_t)rt->cpu.ss<<4)+sp;
    if(a<=0x10fff9u) {
        const uint8_t *m=rt->cpu.memory;
        const uint16_t rip=(uint16_t)m[a]|((uint16_t)m[a+1]<<8);
        const uint16_t rcs=(uint16_t)m[a+2]|((uint16_t)m[a+3]<<8);
        const uint16_t rfl=(uint16_t)m[a+4]|((uint16_t)m[a+5]<<8);
        const int frame=sp==(uint16_t)(bb622_post_sp-6u) &&
                         rt->cpu.ss==bb622_post_ss && rip==bb622_post_ip &&
                         rcs==bb622_post_cs && rfl==bb622_post_flags;
        printf("[bb622-postirq] FRAME %s saved=%04X:%04X FLAGS=%04X "
               "expected=%04X:%04X FLAGS=%04X SP=%04X->%04X\n",
               frame?"MATCH":"MISMATCH",(unsigned)rcs,(unsigned)rip,(unsigned)rfl,
               (unsigned)bb622_post_cs,(unsigned)bb622_post_ip,(unsigned)bb622_post_flags,
               (unsigned)bb622_post_sp,(unsigned)sp);
        fflush(stdout);
    }else { printf("[bb622-postirq] FRAME inaccessible at %05lX\n",(unsigned long)a);fflush(stdout); }
}
static void bb622_post_slice(MdRuntime *rt, const char *where) {
    if(!bb622_post_active || bb622_post_samples>=16u) return;
    ++bb622_post_samples;
    bb622_post_dump(rt,where);
    if(bb622_post_samples==16u) { printf("[bb622-postirq] TRACE-END limit=16 slices\n");fflush(stdout); }
}
#endif
