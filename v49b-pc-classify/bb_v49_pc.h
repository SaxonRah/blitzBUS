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
/* Called only from the interrupt context: write one PC and nothing else. */
__attribute__((noinline,used)) static void bb49_capture(uint32_t pc) {
    if (!bb49_enabled) return;
    bb49_pc[bb49_seq & (BB49_COUNT-1u)] = pc;
    bb49_seq++;
}
/* Naked entry: basic frame at MSP/PSP; extended FP frames include
 * 72 bytes before the eight-word integer exception frame.
 * The interrupted PC sits 24 bytes into that integer frame. */
__attribute__((naked,used)) static void bb49_handler(void) {
    __asm volatile(
       "tst lr, #4\n"
       "ite eq\n"
       "mrseq r0, msp\n"
       "mrsne r0, psp\n"
       "tst lr, #0x10\n"
       "it eq\n"
       "addeq r0, r0, #72\n"
       "ldr r0, [r0, #24]\n"
       "b bb49_capture\n"
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
/* v49b: reporting-only region classification and raw-PC evidence.
 * Safe: no lookup, printf or allocation in the interrupt handler. */
static const char *bb49_region(uint32_t pc) {
    if (pc >= 0x20000000u && pc < 0x20080000u) return "SRAM";
    if (pc >= 0x10000000u && pc < 0x11000000u) return "XIP-FLASH";
    if (pc >= 0x11000000u && pc < 0x12000000u) return "PSRAM";
    if (pc >= 0x00000000u && pc < 0x02000000u) return "LOW-ALIAS";
    if (pc >= 0xE0000000u) return "SYSTEM";
    return "OTHER";
}
static void bb49_report(struct B86Jit *jit) {
    volatile uint32_t * const systick=(volatile uint32_t*)0xE000E010u;
    volatile uint32_t * const vtor=(volatile uint32_t*)0xE000ED08u;
    volatile uint32_t * const icsr=(volatile uint32_t*)0xE000ED04u;
    uint32_t stop=bb49_seq;
    uint32_t first=bb49_previous;
    if (!bb49_enabled) {
        if(!bb49_ignored++)printf("[bb-v49-pc] inactive status=%lu\n",(unsigned long)bb49_status);
        return;
    }
    uint32_t missed=stop-first>BB49_COUNT?stop-first-BB49_COUNT:0u;
    if(missed)first=stop-BB49_COUNT;
    /* Freeze the sampler while reading ring slots: bounded report work only. */
    bb49_enabled=0;
    __asm volatile("dmb sy" ::: "memory");
    uint32_t regions[6]={0};
    uint32_t mapped=0,unmapped=0;
    uint32_t raw_pc[12]={0},raw_count[12]={0};
    typedef struct {uint32_t key,host,count;} H;
    H top[24]={{0}};
    for(uint32_t i=first;i<stop;i++) {
        uint32_t pc=bb49_pc[i&(BB49_COUNT-1u)]&~1u;
        unsigned region=5;
        if(pc>=0x20000000u && pc<0x20080000u)region=0;
        else if(pc>=0x10000000u && pc<0x11000000u)region=1;
        else if(pc>=0x11000000u && pc<0x12000000u)region=2;
        else if(pc<0x02000000u)region=3;
        else if(pc>=0xE0000000u)region=4;
        regions[region]++;
        unsigned slot=12;
        for(unsigned k=0;k<12;k++) if(raw_count[k] && raw_pc[k]==pc){slot=k;break;}
        if(slot==12)for(unsigned k=0;k<12;k++)if(!raw_count[k]){slot=k;raw_pc[k]=pc;break;}
        if(slot<12)raw_count[slot]++;
        uint32_t key=0,offset=0;
        if(!b86_jit_pc_lookup(jit,(uintptr_t)pc,&key,&offset)){unmapped++;continue;}
        mapped++;
        unsigned found=24;
        for(unsigned j=0;j<24;j++)if(top[j].count && top[j].key==key){found=j;break;}
        if(found==24)for(unsigned j=0;j<24;j++)if(!top[j].count){found=j;break;}
        if(found==24){unsigned lo=0;for(unsigned j=1;j<24;j++)if(top[j].count<top[lo].count)lo=j;top[lo].count--;continue;}
        if(!top[found].count){top[found].key=key;top[found].host=offset;}
        top[found].count++;
    }
    bb49_previous=stop;
    __asm volatile("dmb sy" ::: "memory");
    bb49_enabled=1;
    uintptr_t table=(uintptr_t)*vtor,vector=0;
    if(table>=0x20000000u && table<0x20080000u)vector=((volatile uintptr_t*)table)[15];
    printf("[bb-v49b-state] seq=%lu ctrl=%08lX load=%lu val=%lu icsr=%08lX vector=%08lX expected=%08lX\n",
      (unsigned long)stop,(unsigned long)systick[0],(unsigned long)systick[1],
      (unsigned long)systick[2],(unsigned long)*icsr,(unsigned long)vector,
      (unsigned long)(((uintptr_t)bb49_handler)|1u));
    printf("[bb-v49b-regions] samples=%lu sram=%lu flash=%lu psram=%lu low-alias=%lu system=%lu other=%lu mapped=%lu unmapped=%lu lost=%lu\n",
      (unsigned long)(stop-first),(unsigned long)regions[0],(unsigned long)regions[1],
      (unsigned long)regions[2],(unsigned long)regions[3],(unsigned long)regions[4],
      (unsigned long)regions[5],(unsigned long)mapped,(unsigned long)unmapped,(unsigned long)missed);
    for(unsigned k=0;k<12;k++)if(raw_count[k])
      printf("[bb-v49b-rawpc] pc=%08lX region=%s count=%lu\n",
        (unsigned long)raw_pc[k],bb49_region(raw_pc[k]),(unsigned long)raw_count[k]);
    for(unsigned rank=1;rank<=12;rank++) {
        unsigned best=24;for(unsigned j=0;j<24;j++)if(top[j].count && (best==24||top[j].count>top[best].count))best=j;
        if(best==24)break;
        printf("[bb-v49-pc-block] rank=%u cs=%04lX ip=%04lX samples=%lu example-host-offset=%lu\n",
          rank,(unsigned long)(top[best].key>>16),(unsigned long)(top[best].key&65535u),
          (unsigned long)top[best].count,(unsigned long)top[best].host);
        top[best].count=0;
    }
    fflush(stdout);
}

#else
static void bb49_init(uint32_t ticks){(void)ticks;}
static void bb49_report(struct B86Jit *jit){(void)jit;}
#endif
#endif
