#ifndef BB622_IRQ0_STEPTRACE_H
#define BB622_IRQ0_STEPTRACE_H
/* BB622_IRQ0_STEPTRACE_V2: one-shot IRQ0 yield-resilient diagnostic only.
 * For at most 64 guest steps after Ctrl+U, execute via existing blitz86
 * interpreter and trace each instruction. Neither PIC scheduling nor guest
 * interrupt state is changed. Original JIT resumes when the window ends. Host yields are logged and tracing resumes on the next guest slice.
 */
#include <stdint.h>
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
static uint8_t bb622_steptrace_left;
static uint8_t bb622_steptrace_done;
static uint8_t bb622_steptrace_yields;
static uint64_t bb622_steptrace_started;
static void bb622_steptrace_arm(const MdRuntime *rt) {
    const uint8_t *p=rt->cpu.memory;
    const unsigned v8=(unsigned)p[0x20u]|((unsigned)p[0x21u]<<8);
    const unsigned s8=(unsigned)p[0x22u]|((unsigned)p[0x23u]<<8);
    const unsigned v1c=(unsigned)p[0x70u]|((unsigned)p[0x71u]<<8);
    const unsigned s1c=(unsigned)p[0x72u]|((unsigned)p[0x73u]<<8);
    bb622_steptrace_left=64u;
    bb622_steptrace_done=0u;
    bb622_steptrace_yields=0u;
    bb622_steptrace_started=bb_now_us();
    printf("[bb622-steptrace] ARMED max-insns=64 engine=interpreter "
           "INT08=%04X:%04X INT1C=%04X:%04X "
           "hostbios=%04X guest=%04X:%04X\n",
           s8,v8,s1c,v1c,(unsigned)bios_seg,
           (unsigned)rt->cpu.cs,(unsigned)rt->cpu.ip);
    fflush(stdout);
}
static int bb622_steptrace_active(void) {
    if (!bb622_steptrace_left) return 0;
    if (bb_now_us()-bb622_steptrace_started > 8000000ull) {
        bb622_steptrace_left=0;
        printf("[bb622-steptrace] END reason=timeout\n");fflush(stdout);
        return 0;
    }
    return 1;
}
static int bb622_steptrace_run(B86Cpu *cpu,uint16_t host_bios_seg) {
    int rc=B86_BUDGET;
    unsigned in_this_slice=0u;
    while(bb622_steptrace_active()) {
        const unsigned cs=(unsigned)(uint16_t)cpu->seg[B86_CS];
        const unsigned ip=(unsigned)(uint16_t)cpu->ip;
        const unsigned ss=(unsigned)(uint16_t)cpu->seg[B86_SS];
        const unsigned sp=(unsigned)(uint16_t)cpu->r[B86_SP];
        if(cs==host_bios_seg) {
            printf("[bb622-steptrace] BIOS-HANDOFF CS:IP=%04X:%04X "
                   "hostbios=%04X steps-left=%u\n",cs,ip,
                   (unsigned)host_bios_seg,(unsigned)bb622_steptrace_left);
            fflush(stdout);bb622_steptrace_left=0;
            return B86_TRAP;
        }
        unsigned lin=((cs<<4u)+ip)&cpu->amask;
        unsigned op0=0,op1=0,op2=0,op3=0;
        if(lin < B86_MEM_BYTES-4u) {
            op0=*b86_host(cpu,lin);
            op1=*b86_host(cpu,lin+1u);
            op2=*b86_host(cpu,lin+2u);
            op3=*b86_host(cpu,lin+3u);
        }
        const unsigned flags=(unsigned)b86_get_flags(cpu);
        const unsigned n=65u-(unsigned)bb622_steptrace_left;
        const int step_rc=b86_step(cpu);
        if(step_rc==B86_OK) ++cpu->icnt;
        printf("[bb622-steptrace] #%02u %04X:%04X op=%02X%02X%02X%02X "
               "SS:SP=%04X:%04X FL=%04X "
               "-> %04X:%04X SS:SP=%04X:%04X rc=%d irq=%08lX "
               "AX=%04X DX=%04X BP=%04X DS=%04X ES=%04X "
               "ISR=%02X EOI=%llu\n",
               n,cs,ip,op0,op1,op2,op3,ss,sp,flags,
               (unsigned)(uint16_t)cpu->seg[B86_CS],(unsigned)(uint16_t)cpu->ip,
               (unsigned)(uint16_t)cpu->seg[B86_SS],(unsigned)(uint16_t)cpu->r[B86_SP],
               step_rc,(unsigned long)cpu->irq,
               (unsigned)(uint16_t)cpu->r[B86_AX],
               (unsigned)(uint16_t)cpu->r[B86_DX],
               (unsigned)(uint16_t)cpu->r[B86_BP],
               (unsigned)(uint16_t)cpu->seg[B86_DS],
               (unsigned)(uint16_t)cpu->seg[B86_ES],
               (unsigned)bb_irq36.isr,(unsigned long long)bb_irq36.eois);
        fflush(stdout);
        --bb622_steptrace_left;
        ++bb622_steptrace_done;
        ++in_this_slice;
        if(step_rc != B86_OK) {
            bb622_steptrace_left=0;
            printf("[bb622-steptrace] END reason=step-rc rc=%d\n",step_rc);
            fflush(stdout);
            return step_rc;
        }
        if(cpu->irq) {
            ++bb622_steptrace_yields;
            printf("[bb622-steptrace] HOST-YIELD irq=%08lX left=%u done=%u yields=%u "
                   "next=%04X:%04X (trace retained)\n",
                   (unsigned long)cpu->irq,(unsigned)bb622_steptrace_left,
                   (unsigned)bb622_steptrace_done,(unsigned)bb622_steptrace_yields,
                   (unsigned)(uint16_t)cpu->seg[B86_CS],
                   (unsigned)(uint16_t)cpu->ip);
            fflush(stdout);
            return B86_EXIT;
        }
        /* Keep the normal guest scheduler active even during slow USB logging. */
        if(in_this_slice>=4u && bb622_steptrace_left) {
            printf("[bb622-steptrace] SLICE-PAUSE left=%u done=%u next=%04X:%04X\n",
                   (unsigned)bb622_steptrace_left,(unsigned)bb622_steptrace_done,
                   (unsigned)(uint16_t)cpu->seg[B86_CS],
                   (unsigned)(uint16_t)cpu->ip);
            fflush(stdout);
            return B86_BUDGET;
        }
    }
    printf("[bb622-steptrace] END reason=window-complete next=%04X:%04X "
           "retired=%lu; JIT resumes next slice\n",
           (unsigned)(uint16_t)cpu->seg[B86_CS],(unsigned)(uint16_t)cpu->ip,
           (unsigned long)bb622_steptrace_done);
    fflush(stdout);
    return rc;
}
#endif /* PICO_ON_DEVICE */
#endif /* BB622_IRQ0_STEPTRACE_H */
