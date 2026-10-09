#ifndef BB_V36_IRQ_H
#define BB_V36_IRQ_H
/* v36: single-master 8259 PIC + PIT ch0 IRQ0 edge scheduling.
 * No asynchronous guest state writes. Caller polls at CPU slice boundaries.
 * IRQ edges while IRR already set are coalesced, as on an edge-triggered PIC.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "bb_pit.h"
typedef struct BbIrq36 {
 uint64_t anchor_us, scheduled, edges, delivered, masked, if_blocked, eois, coalesced;
 uint32_t trace;
 uint8_t imr, irr, isr, base, init_step, icw1, expect_icw4, auto_eoi, read_isr, active;
} BbIrq36;
static BbIrq36 bb_irq36;
/* v37: sampling profiler. Times include host/JIT scheduling and clock overhead.
 * EOI latency spans guest IRQ entry through the PIC acknowledgment and does
 * NOT represent exclusive CPU time inside the interrupt handler. */
extern uint64_t bb_now_us(void);
static uint64_t bb_v37_inject_us, bb_v37_eoi_sum_us, bb_v37_eoi_max_us;
static uint64_t bb_v37_eoi_samples, bb_v37_dispatch_samples;
static uint64_t bb_v37_dispatch_sum_us, bb_v37_dispatch_max_us;
static uint64_t bb_v37_dispatch_polls, bb_v37_pending_eoi;
static uint64_t bb_v37_eoi_hist[6];
static uint64_t bb_v37_poll_start;
static void bb_v37_poll_begin(void) {
 ++bb_v37_dispatch_polls;
 bb_v37_poll_start = ((bb_v37_dispatch_polls & 127u)==0u) ? bb_now_us() : 0u;
}
static void bb_v37_poll_end(void) {
 if(bb_v37_poll_start){
  uint64_t dt=bb_now_us()-bb_v37_poll_start;
  bb_v37_dispatch_sum_us+=dt;
  if(dt>bb_v37_dispatch_max_us)bb_v37_dispatch_max_us=dt;
  ++bb_v37_dispatch_samples;
 }
}
static void bb_v37_record_eoi(void){
 if(bb_v37_pending_eoi){
  uint64_t dt=bb_now_us()-bb_v37_inject_us;
  bb_v37_eoi_sum_us+=dt;
  if(dt>bb_v37_eoi_max_us)bb_v37_eoi_max_us=dt;
  ++bb_v37_eoi_samples;
  unsigned b=dt<250u?0:dt<500u?1:dt<1000u?2:dt<2000u?3:dt<5000u?4:5;
  ++bb_v37_eoi_hist[b];
  bb_v37_pending_eoi=0;
 }
}

static void bb_irq36_init(uint64_t now){memset(&bb_irq36,0,sizeof bb_irq36);bb_irq36.anchor_us=now;bb_irq36.base=8;bb_v37_inject_us=bb_v37_eoi_sum_us=bb_v37_eoi_max_us=bb_v37_eoi_samples=bb_v37_dispatch_samples=0;bb_v37_dispatch_sum_us=bb_v37_dispatch_max_us=bb_v37_dispatch_polls=bb_v37_pending_eoi=0;memset(bb_v37_eoi_hist,0,sizeof bb_v37_eoi_hist);bb_v37_poll_start=0;}
static int bb_irq36_in(uint16_t port,uint8_t *val){
 if(port==0x20){*val=bb_irq36.read_isr?bb_irq36.isr:bb_irq36.irr;return 1;}
 if(port==0x21){*val=bb_irq36.imr;return 1;}
 return 0;
}
static int bb_irq36_out(uint16_t port,uint8_t val){
 if(port==0x21){
  if(bb_irq36.init_step==1){bb_irq36.base=val&0xf8u;bb_irq36.init_step=(bb_irq36.icw1&2u)?(bb_irq36.expect_icw4?3u:0u):2u;}
  else if(bb_irq36.init_step==2){bb_irq36.init_step=bb_irq36.expect_icw4?3u:0u;}
  else if(bb_irq36.init_step==3){bb_irq36.auto_eoi=(val&2u)!=0;bb_irq36.init_step=0;}
  else bb_irq36.imr=val;
  return 1;
 }
 if(port!=0x20)return 0;
 if(val&0x10u){ /* ICW1 initialization */
  bb_irq36.icw1=val;bb_irq36.expect_icw4=(val&1u)!=0;
  bb_irq36.init_step=1;bb_irq36.imr=bb_irq36.irr=bb_irq36.isr=0;bb_irq36.read_isr=0;
 }else if((val&0x18u)==0x08u){ /* OCW3 */
  if(val&2u)bb_irq36.read_isr=val&1u;
 }else if(val&0x20u){ /* OCW2 EOI */
  if(val&0x40u)bb_irq36.isr&=(uint8_t)~(1u<<(val&7u));
  else {for(unsigned i=0;i<8;i++)if(bb_irq36.isr&(1u<<i)){bb_irq36.isr&=(uint8_t)~(1u<<i);break;}}
  bb_irq36.eois++;
  bb_v37_record_eoi();
 }
 return 1;
}
static void bb_irq36_schedule(uint64_t now){
 BbPitChannel *c=&bb_pit.c[0];
 uint32_t reload=c->reload_raw?c->reload_raw:65536u;
 if(bb_irq36.anchor_us!=c->epoch_us){bb_irq36.anchor_us=c->epoch_us;bb_irq36.scheduled=0;}
 if(now<c->epoch_us)return;
 uint64_t periods=((now-c->epoch_us)*1193182ull)/(1000000ull*reload);
 if(periods<=bb_irq36.scheduled)return;
 uint64_t due=periods-bb_irq36.scheduled;bb_irq36.scheduled=periods;bb_irq36.edges+=due;
 if(bb_irq36.irr&1u)bb_irq36.coalesced+=due;
 else {bb_irq36.irr|=1u;if(due>1)bb_irq36.coalesced+=due-1;}
}
static int bb_irq36_dispatch(MdRuntime *rt,uint64_t now){
 bb_v37_poll_begin();
 bb_irq36_schedule(now);
 if(!(bb_irq36.irr&1u)){bb_v37_poll_end();return 0;}
 if(bb_irq36.imr&1u){bb_irq36.masked++;bb_v37_poll_end();return 0;}
 if(bb_irq36.isr&1u){bb_v37_poll_end();return 0;}
 MdX86 *c=&rt->cpu;
 uint16_t flags=md_x86_flags(c);
 if(!(flags&0x200u)){bb_irq36.if_blocked++;bb_v37_poll_end();return 0;}
 uint16_t return_cs=c->cs, return_ip=c->ip;
 uint32_t vec=(uint32_t)bb_irq36.base;
 uint8_t *m=c->memory;
 uint16_t ip=(uint16_t)(m[vec*4]|((uint16_t)m[vec*4+1]<<8));
 uint16_t cs=(uint16_t)(m[vec*4+2]|((uint16_t)m[vec*4+3]<<8));
 /* Don't force execution through a null interrupt vector. */
 if(!(ip|cs)){bb_v37_poll_end();return 0;}
 bb_irq36.irr&=(uint8_t)~1u;
 if(!bb_irq36.auto_eoi)bb_irq36.isr|=1u;
 md_x86_push(c,flags);
 md_x86_push(c,c->cs);
 md_x86_push(c,c->ip);
 md_x86_set_flags(c,(uint16_t)(flags&~0x0300u));
 c->cs=cs;c->ip=ip;
 bb_irq36.delivered++;
 bb_v37_inject_us=now;bb_v37_pending_eoi=!bb_irq36.auto_eoi;
 bb_v37_poll_end();
 if(bb_irq36.trace++<24u){printf("[bb-v36-irq] IRQ0 INT%02X handler=%04X:%04X return=%04X:%04X flags=%04X imr=%02X isr=%02X\n",(unsigned)vec,cs,ip,(unsigned)return_cs,(unsigned)return_ip,flags,bb_irq36.imr,bb_irq36.isr);fflush(stdout);}
 return 1;
}
static void bb_v37_irq_report(void){
 printf("[bb-v37-irq-profile] polls=%llu sampled=%llu poll-us-sum=%llu poll-us-max=%llu eoi-samples=%llu eoi-us-sum=%llu eoi-us-max=%llu outstanding=%llu hist-us=<250:%llu,250-499:%llu,500-999:%llu,1000-1999:%llu,2000-4999:%llu,5000+:%llu\n",
 (unsigned long long)bb_v37_dispatch_polls,(unsigned long long)bb_v37_dispatch_samples,
 (unsigned long long)bb_v37_dispatch_sum_us,(unsigned long long)bb_v37_dispatch_max_us,
 (unsigned long long)bb_v37_eoi_samples,(unsigned long long)bb_v37_eoi_sum_us,
 (unsigned long long)bb_v37_eoi_max_us,(unsigned long long)bb_v37_pending_eoi,
 (unsigned long long)bb_v37_eoi_hist[0],(unsigned long long)bb_v37_eoi_hist[1],
 (unsigned long long)bb_v37_eoi_hist[2],(unsigned long long)bb_v37_eoi_hist[3],
 (unsigned long long)bb_v37_eoi_hist[4],(unsigned long long)bb_v37_eoi_hist[5]);
}
static void bb_irq36_report(void){
 printf("[bb-v36-irq-summary] edges=%llu delivered=%llu coalesced=%llu masked-polls=%llu if0-polls=%llu eoi=%llu irr=%02X imr=%02X isr=%02X base=%02X\n",(unsigned long long)bb_irq36.edges,(unsigned long long)bb_irq36.delivered,(unsigned long long)bb_irq36.coalesced,(unsigned long long)bb_irq36.masked,(unsigned long long)bb_irq36.if_blocked,(unsigned long long)bb_irq36.eois,bb_irq36.irr,bb_irq36.imr,bb_irq36.isr,bb_irq36.base);
 bb_v37_irq_report();
}
#endif
