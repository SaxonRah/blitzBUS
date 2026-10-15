/* BB_IRQ0_BRIDGE_V2: hosted interpreter + real handoff regression.
 * Compile against the ACTUAL current microDOS runtime and blitz86 interpreter.
 * NO guest DOS images, no Pico, no native Thumb-2 JIT execution here.
 */
#include "microdos/runtime.h"
#include "b86.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks=0, failures=0;
#define T(E) do { ++checks; if(!(E)) { fprintf(stderr,"FAIL %s:%d: %s\n",__FILE__,__LINE__,#E); ++failures; } } while(0)
#define EXIT_ON_ERROR(E) do { if (!(E)) { fprintf(stderr, "ERROR: %s\n", #E); exit(3); } } while(0)

static const uint16_t IV=8, HCS=0x0e2a, HIP=0x003c, RCS=0x0ff2, RIP=0x87a2, SS=0x0e51;
static const uint16_t FLAGS=0x0303; /* IF, TF, CF and mandatory bit 1. */
static const uint8_t HANDLER[]={0x50,0xB8,0x34,0x12,0x58,0xCF}; /* PUSH AX; MOV AX,1234; POP AX; IRET */

static void fixture(MdRuntime *rt,uint8_t *memory,uint16_t sp) {
    MdHooks hooks={0};
    memset(memory,0,B86_MEM_BYTES);
    md_runtime_init(rt,memory,&hooks);
    rt->cpu.cs=RCS;rt->cpu.ip=RIP;rt->cpu.ss=SS;rt->cpu.ds=0x3200;rt->cpu.es=0x3400;
    rt->cpu.r[MD_X86_SP]=sp;
    rt->cpu.r[MD_X86_AX]=0xA55A;rt->cpu.r[MD_X86_BX]=0xBEEF;
    rt->cpu.r[MD_X86_CX]=0xC025;rt->cpu.r[MD_X86_DX]=0xD123;
    md_x86_set_flags(&rt->cpu,FLAGS);
    md_x86_write16_linear(&rt->cpu,4u*IV,HIP);
    md_x86_write16_linear(&rt->cpu,4u*IV+2u,HCS);
    for(size_t i=0;i<sizeof HANDLER;++i)md_x86_write8(&rt->cpu,HCS,(uint16_t)(HIP+i),HANDLER[i]);
    md_x86_write8(&rt->cpu,RCS,RIP,0xF4); /* Return sentinel. */
}

/* Exact CPU state transfer pattern in current blitzBUS/src/bb_live.c. */
static void to_blitz(B86Cpu *c,MdRuntime *rt){
    MdX86 *m=&rt->cpu;
    for(unsigned i=0;i<8;++i)c->r[i]=m->r[i];
    b86_set_seg(c,B86_ES,m->es);b86_set_seg(c,B86_CS,m->cs);
    b86_set_seg(c,B86_SS,m->ss);b86_set_seg(c,B86_DS,m->ds);
    c->ip=m->ip;b86_set_flags(c,md_x86_flags(m));
}
static void to_micro(B86Cpu *c,MdRuntime *rt){
    MdX86 *m=&rt->cpu;
    for(unsigned i=0;i<8;++i)m->r[i]=(uint16_t)c->r[i];
    m->es=(uint16_t)c->seg[B86_ES];m->cs=(uint16_t)c->seg[B86_CS];
    m->ss=(uint16_t)c->seg[B86_SS];m->ds=(uint16_t)c->seg[B86_DS];
    m->ip=(uint16_t)c->ip;md_x86_set_flags(m,b86_get_flags(c));
}

/* Real (non-mock) blitzBUS PIC entry order, using the microDOS memory helpers.
 * No PIC clock scheduling here. This tests the post-arbitration IRQ entry.
 */
static void pic_entry(MdRuntime *rt){
    MdX86 *m=&rt->cpu;
    const uint16_t f=md_x86_flags(m);
    const uint32_t vec=(uint32_t)IV*4u;
    const uint16_t ip=md_x86_read16_linear(m,vec);
    const uint16_t cs=md_x86_read16_linear(m,vec+2u);
    T(ip==HIP && cs==HCS);
    md_x86_push(m,(uint16_t)(f&0x0FFFu));
    md_x86_push(m,m->cs);md_x86_push(m,m->ip);
    md_x86_set_flags(m,(uint16_t)(f&~0x0300u));
    m->cs=cs;m->ip=ip;
}

static void check_state(const char *case_name,unsigned instruction,MdRuntime *ref,MdRuntime *got) {
    MdX86 *a=&ref->cpu,*b=&got->cpu;
    if(a->cs!=b->cs||a->ip!=b->ip||a->r[MD_X86_SP]!=b->r[MD_X86_SP])
        printf("MISMATCH %s instruction=%u REF=%04X:%04X SP=%04X B86=%04X:%04X SP=%04X\n",
          case_name,instruction,(unsigned)a->cs,(unsigned)a->ip,(unsigned)a->r[MD_X86_SP],
          (unsigned)b->cs,(unsigned)b->ip,(unsigned)b->r[MD_X86_SP]);
    T(a->cs==b->cs);T(a->ip==b->ip);T(a->ss==b->ss);
    T(a->ds==b->ds);T(a->es==b->es);
    T(a->r[MD_X86_SP]==b->r[MD_X86_SP]);
    for(unsigned i=0;i<8;++i)T(a->r[i]==b->r[i]);
    T((md_x86_flags(a)&0x0FFFu)==(md_x86_flags(b)&0x0FFFu));
}

static void run_case(const char *label,uint16_t sp,unsigned model,int per_step) {
    MdRuntime *ref=(MdRuntime *)calloc(1,sizeof(MdRuntime));
    MdRuntime *md=(MdRuntime *)calloc(1,sizeof(MdRuntime));
    B86Cpu *b=(B86Cpu *)calloc(1,sizeof(B86Cpu));
    uint8_t *a=(uint8_t *)calloc(1,B86_MEM_BYTES);
    uint8_t *mem=(uint8_t *)calloc(1,B86_MEM_BYTES);
    EXIT_ON_ERROR(ref&&md&&b&&a&&mem);
    fixture(ref,a,sp);fixture(md,mem,sp);
    T(!md_runtime_interrupt(ref,(uint8_t)IV));
    pic_entry(md);
    T(ref->cpu.r[MD_X86_SP]==md->cpu.r[MD_X86_SP]);
    for(unsigned i=0;i<6;i+=2){const uint16_t off=(uint16_t)(sp-6u+i);
      T(md_x86_read16(&ref->cpu,SS,off)==md_x86_read16(&md->cpu,SS,off));}
    b86_init(b,mem);b->model=model;
    to_blitz(b,md);
    for(unsigned i=0;i<4;++i){
        T(md_interp_step(ref)==MD_STOP_NONE);
        T(b86_step(b)==B86_OK);
        if(per_step||i==3){
           to_micro(b,md);
           check_state(label,i,ref,md);
           if(per_step&&i<3)to_blitz(b,md);
        }
    }
    T(md->cpu.cs==RCS && md->cpu.ip==RIP);
    T(md->cpu.r[MD_X86_SP]==sp);
    T(md->cpu.r[MD_X86_AX]==0xA55A);
    T((md_x86_flags(&md->cpu)&0x0FFFu)==FLAGS);
    printf("PASS %s model=%u SP=%04X handoff=%s return=%04X:%04X FLAGS=%04X\n",
      label,model,sp,per_step?"every-step":"one-slice",md->cpu.cs,md->cpu.ip,
      (unsigned)(md_x86_flags(&md->cpu)&0x0FFFu));
    free(ref);free(md);free(b);free(a);free(mem);
}

static void corrupted_frame_control(void) {
    MdRuntime *md=(MdRuntime *)calloc(1,sizeof(MdRuntime));
    B86Cpu *b=(B86Cpu *)calloc(1,sizeof(B86Cpu));
    uint8_t *mem=(uint8_t *)calloc(1,B86_MEM_BYTES);
    EXIT_ON_ERROR(md&&b&&mem);
    fixture(md,mem,0xE214u);
    pic_entry(md);
    b86_init(b,mem);b->model=B86_CPU_286;to_blitz(b,md);
    const uint16_t save_sp=(uint16_t)b->r[B86_SP];
    /* Deliberately overwrite the return IP+CS only. Not a real bug reproduction. */
    md_x86_write16(&md->cpu,SS,save_sp,0);
    md_x86_write16(&md->cpu,SS,(uint16_t)(save_sp+2),0);
    /* Skip the synthetic handler prologue and execute its IRET. */
    b->ip=HIP+5u;
    T(b86_step(b)==B86_OK);
    to_micro(b,md);
    T(md->cpu.cs==0 && md->cpu.ip==0);
    printf("EXPECTED corruption control -> %04X:%04X (not evidence of cause)\n",md->cpu.cs,md->cpu.ip);
    free(md);free(b);free(mem);
}

int main(void){
    printf("blitzBUS IRQ0 V2: microDOS interpreter vs actual blitz86 interpreter + handoff\n");
    for(unsigned m=0;m<3;++m){
        const unsigned model=m==0?B86_CPU_8086:m==1?B86_CPU_286:B86_CPU_386;
        run_case("ordinary",0xE214u,model,0);
        run_case("ordinary",0xE214u,model,1);
        run_case("SP wrap 0004",0x0004u,model,0);
        run_case("SP wrap 0004",0x0004u,model,1);
        run_case("SP wrap 0000",0x0000u,model,0);
        run_case("SP wrap 0000",0x0000u,model,1);
    }
    corrupted_frame_control();
    printf("RESULT %u checks %u failures\n",checks,failures);
    if(failures){puts("FAIL: no new Pico IRQ0 trial");return 1;}
    puts("PASS: real interpreter and state handoff; NOT a native Thumb-2 JIT test.");
    return 0;
}
