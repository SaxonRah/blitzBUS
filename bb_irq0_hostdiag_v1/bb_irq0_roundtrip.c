/* blitzBUS IRQ0 hosted boundary regression, version 1.
 * No DOS image, Pico, COM port, or firmware touched.
 * Build against the actual microdos_runtime library.
 */
#include "microdos/runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static unsigned checks, failures;
#define CHECK(expr) do { ++checks; if (!(expr)) { \
  fprintf(stderr, "FAIL %s:%u: %s\n", __FILE__, (unsigned)__LINE__, #expr); \
  ++failures; \
} } while (0)

static const uint16_t kVector=8u, kHandlerCS=0x0e2au, kHandlerIP=0x003cu;
static const uint16_t kReturnCS=0x0ff2u, kReturnIP=0x87a2u, kSS=0x0e51u;
static const uint16_t kFlags=0x0303u; /* IF+TF+CF; FLAGS bit1 reserved */

static void init_fixture(MdRuntime *rt, uint8_t *memory, uint16_t sp) {
  MdHooks hooks={0};
  memset(memory,0,MD_X86_ADDRESS_SPACE);
  md_runtime_init(rt,memory,&hooks);
  rt->cpu.cs=kReturnCS; rt->cpu.ip=kReturnIP;
  rt->cpu.ss=kSS; rt->cpu.r[MD_X86_SP]=sp;
  md_x86_set_flags(&rt->cpu,kFlags);
  md_x86_write16_linear(&rt->cpu,4u*kVector,kHandlerIP);
  md_x86_write16_linear(&rt->cpu,4u*kVector+2u,kHandlerCS);
  md_x86_write8(&rt->cpu,kHandlerCS,kHandlerIP,0xCFu); /* IRET */
  /* If incorrect state resumes here, the interpreter can safely HLT. */
  md_x86_write8(&rt->cpu,kReturnCS,kReturnIP,0xF4u);
}

/* Exact basic push/set/transfer order currently used in src/bb_irq.h.
   PIC arbitration and 286 high-FLAGS masking are deliberately not emulated:
   fixture uses only low 12 FLAGS bits so expected frame is identical. */
static void blitzbus_pic_entry(MdRuntime *rt) {
  MdX86 *c=&rt->cpu;
  const uint16_t flags=md_x86_flags(c);
  const uint32_t vec=kVector;
  const uint16_t ip=md_x86_read16_linear(c,vec*4u);
  const uint16_t cs=md_x86_read16_linear(c,vec*4u+2u);
  md_x86_push(c,(uint16_t)(flags & 0x0fffu));
  md_x86_push(c,c->cs);
  md_x86_push(c,c->ip);
  md_x86_set_flags(c,(uint16_t)(flags & (uint16_t)~0x0300u));
  c->cs=cs;c->ip=ip;
}

static void check_frame(MdRuntime *rt,uint16_t entry_sp) {
  MdX86 *c=&rt->cpu;
  const uint16_t sp=(uint16_t)(entry_sp-6u);
  CHECK(c->r[MD_X86_SP]==sp);
  CHECK(c->cs==kHandlerCS && c->ip==kHandlerIP);
  CHECK(md_x86_read16(c,kSS,sp)==kReturnIP);
  CHECK(md_x86_read16(c,kSS,(uint16_t)(sp+2u))==kReturnCS);
  CHECK(md_x86_read16(c,kSS,(uint16_t)(sp+4u))==kFlags);
  CHECK((md_x86_flags(c)&0x0300u)==0u);
  CHECK(md_x86_read8(c,kHandlerCS,kHandlerIP)==0xCFu);
}

static void check_iret(MdRuntime *rt,uint16_t entry_sp) {
  MdX86 *c=&rt->cpu;
  MdStopReason result=md_interp_step(rt);
  CHECK(result==MD_STOP_NONE);
  CHECK(c->cs==kReturnCS && c->ip==kReturnIP);
  CHECK(c->r[MD_X86_SP]==entry_sp);
  CHECK(md_x86_flags(c)==kFlags);
  printf("  return CS:IP=%04X:%04X SS:SP=%04X:%04X FLAGS=%04X\n",
        (unsigned)c->cs,(unsigned)c->ip,(unsigned)c->ss,
        (unsigned)c->r[MD_X86_SP],(unsigned)md_x86_flags(c));
}

static void run_case(const char *label,uint16_t sp) {
  uint8_t *m1=(uint8_t *)calloc(1u,MD_X86_ADDRESS_SPACE);
  uint8_t *m2=(uint8_t *)calloc(1u,MD_X86_ADDRESS_SPACE);
  MdRuntime *a=(MdRuntime *)calloc(1u,sizeof(MdRuntime));
  MdRuntime *b=(MdRuntime *)calloc(1u,sizeof(MdRuntime));
  if(!m1||!m2||!a||!b){fprintf(stderr,"Out of host memory\n");exit(3);}
  printf("CASE %s, entry SP=%04X\n",label,(unsigned)sp);
  init_fixture(a,m1,sp);
  init_fixture(b,m2,sp);
  CHECK(!md_runtime_interrupt(a,(uint8_t)kVector)); /* unclaimed vector */
  blitzbus_pic_entry(b);
  check_frame(a,sp);
  check_frame(b,sp);
  CHECK(a->cpu.r[MD_X86_SP]==b->cpu.r[MD_X86_SP]);
  CHECK(a->cpu.cs==b->cpu.cs && a->cpu.ip==b->cpu.ip);
  CHECK(md_x86_flags(&a->cpu)==md_x86_flags(&b->cpu));
  for(unsigned i=0;i<6u;i+=2u){
    uint16_t off=(uint16_t)(sp-6u+i);
    CHECK(md_x86_read16(&a->cpu,kSS,off)==md_x86_read16(&b->cpu,kSS,off));
  }
  check_iret(a,sp);
  check_iret(b,sp);
  free(a);free(b);free(m1);free(m2);
}

/* A deliberately corrupted frame reproduces the zero CS:IP symptom.
   This does NOT assert that corruption caused the real Descent failure. */
static void run_corruption_control(void) {
  uint8_t *m=(uint8_t *)calloc(1u,MD_X86_ADDRESS_SPACE);
  MdRuntime *rt=(MdRuntime *)calloc(1u,sizeof(MdRuntime));
  if(!m||!rt){fprintf(stderr,"Out of host memory\n");exit(3);}
  init_fixture(rt,m,0xe214u);
  blitzbus_pic_entry(rt);
  uint16_t sp=rt->cpu.r[MD_X86_SP];
  md_x86_write16(&rt->cpu,kSS,sp,0u);
  md_x86_write16(&rt->cpu,kSS,(uint16_t)(sp+2u),0u);
  CHECK(md_interp_step(rt)==MD_STOP_NONE);
  CHECK(rt->cpu.cs==0u && rt->cpu.ip==0u);
  printf("CASE intentional frame corruption: IRET -> %04X:%04X (expected control)\n",
        (unsigned)rt->cpu.cs,(unsigned)rt->cpu.ip);
  free(rt);free(m);
}

int main(void) {
  printf("blitzBUS IRQ0 hosted frame/IRET comparison (microDOS runtime linked)\n");
  run_case("ordinary stack",0xe214u);
  run_case("wrap at SP=0004",0x0004u);
  run_case("wrap at SP=0000",0x0000u);
  run_corruption_control();
  printf("RESULT: %u checks; %u failures\n",checks,failures);
  if(failures){puts("FAIL: do not enable guest IRQ0");return 1;}
  puts("PASS: PIC-style entry and canonical INT frame match, interpreter IRET round-trips.");
  puts("LIMIT: does not test blitz86 JIT/native handler execution or DOS 6.22 itself.");
  return 0;
}
