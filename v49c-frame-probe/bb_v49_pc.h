/* v49: opt-in RP2350 Cortex-M33 SysTick interrupted-PC profiler.
 * Only built inside bb_live.c; vector installation requires writable SRAM VTOR.
 * Does not alter DOS PIT/PIC or JIT execution. */
#ifndef BB_V49_PC_H
#define BB_V49_PC_H
#include <stdint.h>
#include <stdio.h>
#include "b86.h"
#if defined(PICO_RP2350) && defined(__arm__) && !defined(__riscv)
#define BB49_COUNT 1024u
static volatile uint32_t bb49_pc[BB49_COUNT];
static volatile uint32_t bb49_seq;
static volatile uint32_t bb49_enabled;
static uint32_t bb49_previous;
static uint32_t bb49_ignored;
static uint32_t bb49_status;
/* v49c: retain only raw exception metadata.  We deliberately do not
 * infer a PC from any offset until its xPSR and frame form are checked.
 * Collection: one in 256 SysTick entries; fixed 8-record ring, no I/O. */
#define BB49_FRAMES 8u
typedef struct {
    uint32_t seq, exc_return, msp, psp, selected;
    uint32_t head[8];
    uint32_t extended[8];
} BB49Frame;
static volatile BB49Frame bb49_frames[BB49_FRAMES];
static volatile uint32_t bb49_frame_seq;
__attribute__((noinline,used)) static void bb49_capture_frame(
        uint32_t *frame, uint32_t exc_return, uint32_t msp, uint32_t psp) {
    if (!bb49_enabled) return;
    uint32_t seq = ++bb49_seq;
    if ((seq & 255u) != 0u) return;
    uint32_t k = bb49_frame_seq & (BB49_FRAMES-1u);
    volatile BB49Frame *d = &bb49_frames[k];
    d->seq = seq;
    d->exc_return = exc_return;
    d->msp = msp;
    d->psp = psp;
    d->selected = (uint32_t)(uintptr_t)frame;
    for (unsigned i=0; i<8; ++i) d->head[i] = frame[i];
    /* Cortex-M extended FP stack frame: core registers begin 18 words
     * after the selected exception frame pointer.  Only read when indicated
     * by EXC_RETURN bit 4; otherwise do not read past the basic frame. */
    if ((exc_return & 0x10u)==0u) {
        for (unsigned i=0; i<8; ++i) d->extended[i] = frame[18+i];
    } else {
        for (unsigned i=0; i<8; ++i) d->extended[i] = 0xFFFFFFFFu;
    }
    __asm volatile("dmb sy" ::: "memory");
    bb49_frame_seq++;
}
/* A naked exception entry must preserve LR=EXC_RETURN and avoid adding a
 * C prologue before reading MSP/PSP.  Branch directly into a C helper;
 * its normal bx lr performs exception return.  r0=chosen SP, r1=LR,
 * r2=MSP and r3=PSP are standard AAPCS arguments. */
__attribute__((naked,used)) static void bb49_handler(void) {
    __asm volatile(
       "mov r1, lr\n"
       "tst r1, #4\n"
       "ite eq\n"
       "mrseq r0, msp\n"
       "mrsne r0, psp\n"
       "mrs r2, msp\n"
       "mrs r3, psp\n"
       "b bb49_capture_frame\n"
    );
}
static void bb49_init(uint32_t reload_ticks) {
    volatile uint32_t * const systick=(volatile uint32_t*)0xE000E010u;
    volatile uint32_t * const vtor=(volatile uint32_t*)0xE000ED08u;
    uintptr_t base=(uintptr_t)(*vtor);
    if (systick[0]&1u) {bb49_status=1;printf("[bb-v49-pc] DISABLED reason=systick-already-active\n");return;}
    if (base<0x20000000u || base>=0x20080000u) {bb49_status=2;printf("[bb-v49-pc] DISABLED reason=vtor-not-sram base=%08lX\n",(unsigned long)base);return;}
    if (reload_ticks<2u || reload_ticks>0x1000000u){bb49_status=3;printf("[bb-v49-pc] DISABLED reason=reload-range\n");return;}
    volatile uintptr_t *vt=(volatile uintptr_t*)base;
    /* Never overwrite a prior non-default SysTick handler (safe conservative
     * policy: require the vector table entry to point outside SRAM). */
    uintptr_t old=vt[15];
    if ((old&~(uintptr_t)1u)>=0x20000000u && (old&~(uintptr_t)1u)<0x20080000u) {
        bb49_status=4;printf("[bb-v49-pc] DISABLED reason=systick-handler-in-sram\n");return;
    }
    vt[15]=((uintptr_t)bb49_handler)|1u;
    __asm volatile("dsb sy\n isb sy" ::: "memory");
    bb49_enabled=1;
    systick[1]=reload_ticks-1u;
    systick[2]=0;
    systick[0]=7u;
    printf("[bb-v49-pc] ENABLED hz=1000 ring=%u vtor=%08lX (opt-in hardware-PC samples)\n",BB49_COUNT,(unsigned long)base);
}
/* v49c frame probe only: no guessed PC mapping or false percentages. */
static void bb49_report(struct B86Jit *jit) {
    (void)jit;
    if (!bb49_enabled) {
        if (!bb49_ignored++) printf("[bb-v49c-frame] inactive status=%lu\n", (unsigned long)bb49_status);
        return;
    }
    /* Disable recording while copying; SysTick remains enabled and active. */
    bb49_enabled=0;
    __asm volatile("dmb sy" ::: "memory");
    uint32_t total=bb49_frame_seq, ticks=bb49_seq;
    volatile uint32_t * const sys=(volatile uint32_t*)0xE000E010u;
    printf("[bb-v49c-status] systick=%lu frames=%lu ctrl=%08lX load=%lu\n",
        (unsigned long)ticks,(unsigned long)total,(unsigned long)sys[0],(unsigned long)sys[1]);
    uint32_t first=total>4u?total-4u:0u;
    for(uint32_t j=first;j<total;j++) {
        volatile const BB49Frame *r=&bb49_frames[j&(BB49_FRAMES-1u)];
        uint32_t lr=r->exc_return;
        unsigned extended=((lr & 0x10u)==0u);
        /* xPSR.T (bit 24) is a useful sanity check, not sufficient proof. */
        uint32_t basepc=r->head[6], basex=r->head[7];
        uint32_t extpc=r->extended[6], extx=r->extended[7];
        printf("[bb-v49c-frame] tick=%lu lr=%08lX msp=%08lX psp=%08lX selected=%08lX fp=%u sec=%u\n",
           (unsigned long)r->seq,(unsigned long)lr,(unsigned long)r->msp,
           (unsigned long)r->psp,(unsigned long)r->selected,extended,
           (unsigned)((lr>>6)&1u));
        printf("[bb-v49c-basic] r0=%08lX r1=%08lX r2=%08lX r3=%08lX r12=%08lX lr=%08lX pc=%08lX xpsr=%08lX T=%u\n",
           (unsigned long)r->head[0],(unsigned long)r->head[1],
           (unsigned long)r->head[2],(unsigned long)r->head[3],
           (unsigned long)r->head[4],(unsigned long)r->head[5],
           (unsigned long)basepc,(unsigned long)basex,(unsigned)((basex>>24)&1u));
        if(extended) printf("[bb-v49c-extended] w18=%08lX w19=%08lX w20=%08lX w21=%08lX w22=%08lX w23=%08lX pc=%08lX xpsr=%08lX T=%u\n",
           (unsigned long)r->extended[0],(unsigned long)r->extended[1],
           (unsigned long)r->extended[2],(unsigned long)r->extended[3],
           (unsigned long)r->extended[4],(unsigned long)r->extended[5],
           (unsigned long)extpc,(unsigned long)extx,(unsigned)((extx>>24)&1u));
    }
    __asm volatile("dmb sy" ::: "memory");
    bb49_enabled=1;
    fflush(stdout);
}

#else
static void bb49_init(uint32_t ticks){(void)ticks;}
static void bb49_report(struct B86Jit *jit){(void)jit;}
#endif
#endif
