/* blitzBUS IRQ0 V3 - real Pico Thumb-2 JIT differential.
 * Read-only to SD/DOS media. Standalone synthetic guest test.
 * C:\blitz86_v2 and C:\microDOS are compiled in place, not edited.
 *
 * Same relevant DOS622 config: B86_CPU_286, B86_PAGED=1,
 * B86_MAXB=2048, B86_MAP_BITS=12, B86_FAST_BITS=10.
 */
#include "b86.h"
#include "b86_hw_alloc.h"
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include "hardware/clocks.h"
#include "hardware/psram.h"
#include <stdio.h>
#include <string.h>
#include <stdint.h>

#ifndef B86_PAGED
#error "V3 must compile with B86_PAGED=1 like DOS622"
#endif

/* Pico B86_PAGED table requires a non-zero >= 0x800 SMC line-map index:
 * exactly the layout already used by blitz86's Pico differential fuzzer.
 */
static uint8_t __uninitialized_psram("bbv3_guest")
    __attribute__((aligned(0x200000)))
    guest_window[0xA0000u+B86_MEM_BYTES];
#define GUEST (guest_window + 0xA0000u)

static uint8_t __attribute__((aligned(64))) codebuf[96u*1024u];
static uint8_t __attribute__((aligned(64))) hotbuf[40u*1024u];
static B86Cpu cpu;
static unsigned eoi_count;
static unsigned checks, fails;

static const uint8_t kHandler[] = {
    0x50,             /* push ax */
    0xB0,0x20,        /* mov al,20h */
    0xE6,0x20,        /* out 20h,al -- EOI */
    0x58,             /* pop ax */
    0xCF              /* IRET */
};
static const uint8_t kReturnCode[] = {
    0x9C,             /* pushf */
    0x5A,             /* pop dx (verify FLAGS immediately after IRET) */
    0xBB,0x00,0x00,   /* mov bx,0 */
    0xB9,0x00,0x01,   /* mov cx,0100h */
    0x43,             /* L: inc bx */
    0xE2,0xFD,       /* loop L */
    0xF4              /* hlt */
};
static uint8_t port_in(B86Cpu *c,uint16_t p){(void)c;(void)p;return 0xFF;}
static void port_out(B86Cpu *c,uint16_t p,uint8_t v){
    (void)c;
    if(p==0x20u && v==0x20u)++eoi_count;
}
static uint32_t linear(uint16_t seg,uint16_t off){
    return (((uint32_t)seg<<4)+off)&0x1FFFFFu;
}
static void put16(uint16_t seg,uint16_t off,uint16_t value){
    /* x86 offsets wrap at 16 bits, even when the linear address does not. */
    GUEST[linear(seg,off)]=(uint8_t)value;
    GUEST[linear(seg,(uint16_t)(off+1u))]=(uint8_t)(value>>8);
}
static uint16_t get16(uint16_t seg,uint16_t off) {
    return (uint16_t)(GUEST[linear(seg,off)]|
                     ((uint16_t)GUEST[linear(seg,(uint16_t)(off+1u))]<<8));
}
struct Result {
    uint16_t regs[8],segments[4],ip,flags;
    uint32_t memhash;
    unsigned eoi;
    int rc;
    unsigned long long blocks, native_insns;
};
static uint32_t memhash(void){
    uint32_t h=2166136261u;
    for(uint32_t k=0;k<B86_MEM_BYTES;k++){h^=GUEST[k];h*=16777619u;}
    return h;
}
static void snapshot(struct Result *s,int rc,const B86JitStats *st) {
    memset(s,0,sizeof *s);
    for(unsigned n=0;n<8;n++)s->regs[n]=(uint16_t)cpu.r[n];
    for(unsigned n=0;n<4;n++)s->segments[n]=(uint16_t)cpu.seg[n];
    s->ip=(uint16_t)cpu.ip;
    s->flags=b86_get_flags(&cpu);
    s->memhash=memhash();
    s->eoi=eoi_count;
    s->rc=rc;
    s->blocks=st?(unsigned long long)st->blocks:0;
    s->native_insns=st?(unsigned long long)st->guest_insns:0;
}
static void check(const char *n,int yes) {
    ++checks;
    if(!yes){++fails;printf("[bb-irq0-v3] FAIL check=%s\n",n);}
}
static void setup(uint16_t initial_sp) {
    const uint16_t ss=0x0E51u, saved_cs=0x0FF2u, saved_ip=0x87A2u;
    const uint16_t saved_flags=0x0303u;
    const uint16_t after=(uint16_t)(initial_sp-6u);
    memset(GUEST,0,B86_MEM_BYTES);
    memcpy(GUEST+linear(0x2000u,0x0100u),kHandler,sizeof kHandler);
    memcpy(GUEST+linear(saved_cs,saved_ip),kReturnCode,sizeof kReturnCode);
    put16(ss,after,saved_ip);
    put16(ss,(uint16_t)(after+2u),saved_cs);
    put16(ss,(uint16_t)(after+4u),saved_flags);
    b86_init(&cpu,GUEST);
    cpu.model=B86_CPU_286;
    cpu.in8=port_in;
    cpu.out8=port_out;
    b86_set_seg(&cpu,B86_CS,0x2000u);
    b86_set_seg(&cpu,B86_SS,ss);
    b86_set_seg(&cpu,B86_DS,0x3000u);
    b86_set_seg(&cpu,B86_ES,0x4000u);
    cpu.ip=0x0100u;
    cpu.r[B86_SP]=after;
    cpu.r[B86_AX]=0xBEEFu;
    cpu.r[B86_BX]=0x1111u;
    b86_set_flags(&cpu,(uint16_t)(saved_flags&~0x0300u));
    eoi_count=0;
    check("initial-frame-ip",get16(ss,after)==saved_ip);
    check("initial-frame-cs",get16(ss,(uint16_t)(after+2u))==saved_cs);
    check("initial-frame-flags",get16(ss,(uint16_t)(after+4u))==saved_flags);
}
static int valid(const struct Result *s,uint16_t initial_sp){
    return s->rc==B86_HALT && s->segments[B86_CS]==0x0FF2u &&
           s->segments[B86_SS]==0x0E51u &&
           s->regs[B86_SP]==initial_sp &&
           s->regs[B86_AX]==0xBEEFu &&
           s->regs[B86_BX]==0x0100u &&
           s->regs[B86_DX]==0x0303u &&
           s->eoi==1u;
}
static int equal_arch(const struct Result *a,const struct Result *b) {
    return memcmp(a->regs,b->regs,sizeof a->regs)==0 &&
           memcmp(a->segments,b->segments,sizeof a->segments)==0 &&
           a->ip==b->ip && a->flags==b->flags &&
           a->memhash==b->memhash && a->eoi==b->eoi &&
           a->rc==b->rc;
}
static void run_case(uint16_t sp,unsigned threshold){
    struct Result reference, translated;
    setup(sp);
    int rc=b86_run_interp(&cpu,200000u);
    snapshot(&reference,rc,NULL);
    check("reference-valid",valid(&reference,sp));
    setup(sp);
    b86_hw_alloc_reset();
    const size_t need=b86_jit_hot_bytes();
    printf("[bb-irq0-v3] jit-hot-tables required=%lu bytes available=%lu bytes\n",
           (unsigned long)need, (unsigned long)sizeof hotbuf);
    if(need>sizeof hotbuf) {
        printf("[bb-irq0-v3] ERROR hotbuf-need=%lu allocated=%lu\n",
              (unsigned long)need,(unsigned long)sizeof hotbuf);
        check("hotbuf-size",0);
        return;
    }
    struct B86Jit *j=b86_jit_create_ex(&cpu,codebuf,sizeof codebuf,
                                       hotbuf,sizeof hotbuf);
    if(!j){check("jit-creation",0);return;}
    b86_jit_set_max_block(j,48u);
    b86_jit_set_hot_threshold(j,threshold);
    b86_jit_set_count_retired(j,1);
    /* Native JIT must actually compile and retire instructions.
       This also exercises interpreter fallback through OUT and IRET. */
    rc=b86_jit_run(&cpu,200000u);
    snapshot(&translated,rc,b86_jit_stats(j));
    int arch_ok=equal_arch(&reference,&translated);
    int values_ok=valid(&translated,sp);
    int native_ok=translated.blocks>0 && translated.native_insns>0;
    check("jit-arch-match",arch_ok);
    check("jit-valid",values_ok);
    check("real-native-code",native_ok);
    printf("[bb-irq0-v3] case=286-paged sp=%04X threshold=%u rc=%d "
           "native-blocks=%llu native-insns=%llu eoi=%u "
           "return=%04X:%04X ss:sp=%04X:%04X dx=%04X "
           "arch=%s valid=%s native=%s\n",
           sp,threshold,rc,translated.blocks,translated.native_insns,
           translated.eoi,translated.segments[B86_CS],translated.ip,
           translated.segments[B86_SS],translated.regs[B86_SP],
           translated.regs[B86_DX],arch_ok?"PASS":"FAIL",
           values_ok?"PASS":"FAIL",native_ok?"PASS":"FAIL");
    if(!arch_ok) {
        printf("[bb-irq0-v3] DIFF ref-hash=%08lX jit-hash=%08lX "
               "ref-ip=%04X jit-ip=%04X ref-flags=%04X jit-flags=%04X\n",
               (unsigned long)reference.memhash,
               (unsigned long)translated.memhash,
               reference.ip,translated.ip,reference.flags,translated.flags);
    }
    b86_jit_destroy(j);
}
static int run_all(void){
    checks=fails=0;
    const uint16_t sp_values[]={0xE214u,0x0004u,0x0000u};
    const unsigned thresholds[]={1u,64u};
    printf("[bb-irq0-v3] BEGIN model=286 B86_PAGED=1 "
           "image=synthetic DOS-no-media\n");
    for(unsigned x=0;x<3;x++)for(unsigned t=0;t<2;t++){
        run_case(sp_values[x],thresholds[t]);
    }
    printf("[bb-irq0-v3] COMPLETE checks=%u failed=%u result=%s\n",
           checks,fails,fails?"FAIL":"PASS");
    stdio_flush();
    return !fails;
}
int main(void) {
    stdio_init_all();
    (void)set_sys_clock_khz(300000,false);
    if(psram_configure_params(PICO_DEFAULT_PSRAM_MAX_FREQ,
                               PICO_DEFAULT_PSRAM_MAX_SELECT,
                               PICO_DEFAULT_PSRAM_MIN_DESELECT)!=0 ||
       psram_reinitialize()!=0){
        while(!stdio_usb_connected())sleep_ms(20);
        printf("[bb-irq0-v3] COMPLETE result=FAIL reason=psram-init\n");
        for(;;)sleep_ms(1000);
    }
    while(!stdio_usb_connected())sleep_ms(20);
    sleep_ms(300);
    if(!psram_is_available() ||
       !psram_check_address(GUEST) ||
       !psram_check_address(GUEST+B86_MEM_BYTES-1u)) {
        printf("[bb-irq0-v3] COMPLETE result=FAIL reason=psram-address\n");
    }else{
        (void)run_all();
    }
    stdio_flush();
    for(;;)sleep_ms(1000);
}
