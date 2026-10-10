/* blitzBUS live backend v0.8: blitz86 owns guest execution.
 *
 *  - microDOS's BIOS segment (device driver trampolines) stays on the
 *    microDOS interpreter: blitz86 stops with B86_TRAP whenever CS reaches it.
 *  - INT n executed by blitz86 goes through microDOS's own hooks.interrupt
 *    (console / disk / clock HLE) with registers synced both ways; a hook
 *    that redirects CS:IP or requests a stop ends the native slice at once.
 *  - IN/OUT go to hooks.in8/out8.
 *  - Memory written behind blitz86's back (disk DMA inside a hook, BIOS
 *    segment interpretation) is detected through microDOS's per-page write
 *    generations (every page is flagged tracked) and invalidated exactly.
 *  - Retired instructions are counted exactly (b86 counted exits) and added
 *    to rt->instructions, so budgets, console polling and MIPS stay correct.
 *  - Slices: on the RP2350 a 1 ms repeating timer sets cpu.irq; on hosts a
 *    dispatch limit bounds each slice.
 */
#include "bb_live.h"
#include "bb_vga.h"
#include "bb_vga.c"
#include "bb_pit.h"
#include "bb_irq.h"
#if defined(BLITZBUS_LCD_CONSOLE) && BLITZBUS_LCD_CONSOLE
#include "bb_lcd_console.h"
#endif
#include "b86.h"
#define BB_V49_PC_PROFILE 1 /* v49 installer opt-in; remove to disable */
#include "bb_v49_pc.h"
#include "msdos2_boot.h"
#include <string.h>
#include <stdio.h>
#ifdef BB_DEBUG
#include <stdio.h>
#endif
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#include "pico/time.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#define BB_HAVE_TIMER 1
#endif

/* microsecond clock, also used by blitz86 for translate time (-DB86_NOW=bb_now_us) */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#include "hardware/structs/xip_ctrl.h"
#include "hardware/watchdog.h"
#include "pico/multicore.h"
extern char __StackBottom[], __StackTop[], __StackOneBottom[], __StackOneTop[];   /* v51 */
#include "hardware/structs/watchdog.h"
uint64_t bb_now_us(void) { return time_us_64(); }
/* v38: XIP/QMI cache counters (flash + PSRAM, both cores). The hardware
   counters SATURATE at 2^32-1 (after ~15 s at 300 MHz the old difference
   read as garbage), so they are read and cleared on every call and
   accumulated in 64 bits. */
static uint64_t xip_acc_miss, xip_acc_access;
uint64_t bb_xip_misses(void)
{
    uint32_t acc = xip_ctrl_hw->ctr_acc, hit = xip_ctrl_hw->ctr_hit;
    xip_ctrl_hw->ctr_acc = 0;
    xip_ctrl_hw->ctr_hit = 0;
    xip_acc_access += acc;
    xip_acc_miss += acc >= hit ? acc - hit : 0u;
    return xip_acc_miss;
}
uint64_t bb_xip_accesses(void) { (void)bb_xip_misses(); return xip_acc_access; }
#else
#include <time.h>
uint64_t bb_xip_misses(void) { return 0; }
uint64_t bb_xip_accesses(void) { return 0; }
uint64_t bb_now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}
#endif

#ifndef BB_TR_PAGES
#define BB_TR_PAGES 24u            /* byte-exact pages (512 B bitmap each, SRAM); v41: 64 -> 24 (DOS runs used 15) */
#endif

#ifndef BB_CODE_BYTES
#define BB_CODE_BYTES (128u * 1024u)
#endif
#ifndef BB_HOT_BYTES
#define BB_HOT_BYTES (96u * 1024u)
#endif
#ifndef BB_SLICE_DISPATCH
#define BB_SLICE_DISPATCH 4096u
#endif
#ifndef BB_SLICE_US
#define BB_SLICE_US 1000
#endif

#if defined(__linux__)
#include <sys/mman.h>
static uint8_t *bb_code;          /* host: needs PROT_EXEC */
#else
static uint8_t bb_code[BB_CODE_BYTES] __attribute__((aligned(64)));   /* RP2350 SRAM is executable */
#endif
static uint8_t bb_hot[BB_HOT_BYTES] __attribute__((aligned(64)));
/* Shadow of translated guest bytes (byte-exact detection of writes made by
   microDOS). 1 MiB+: PSRAM on the RP2350, heap on hosts. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
static uint8_t __uninitialized_psram("bb_shadow") bb_shadow_buf[B86_MEM_BYTES] __attribute__((aligned(64)));
static uint8_t *bb_shadow = bb_shadow_buf;
#else
#include <stdlib.h>
static uint8_t *bb_shadow;
#endif
static const char *fail_reason = "none";

#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
/* blitz86 metadata (block table, map, SMC buckets, RET metadata) is only
   used by the dispatcher: keep it in PSRAM, SRAM goes to the code buffer.
   Build with -DB86_CALLOC=bb_meta_calloc -DB86_FREE=bb_meta_free. */
#ifndef BB_META_BYTES
#define BB_META_BYTES (768u * 1024u)   /* + blitz86 join bitmaps (2 x 136 KiB) and heat table */
#endif
static uint8_t __uninitialized_psram("bb_meta") bb_meta[BB_META_BYTES] __attribute__((aligned(16)));
static size_t bb_meta_used;
void *bb_meta_calloc(size_t n, size_t size)
{
    size_t b = (n * size + 15u) & ~(size_t)15u;
    if (bb_meta_used + b > BB_META_BYTES) return NULL;
    void *p = bb_meta + bb_meta_used;
    bb_meta_used += b;
    memset(p, 0, b);
    return p;
}
void bb_meta_free(void *p) { (void)p; }
#endif
static B86Cpu C;
static void bb_diag_boot_report(void);   /* v42 */
static struct B86Jit *J;
static MdRuntime *R;
static uint16_t bios_seg;
static int enabled = 1, failed = 0;
static uint32_t gen_seen[MD_X86_CODE_PAGE_COUNT];
static BbLiveStats st;
/* byte-exact write filtering inside microDOS: pages holding translated
   bytes get MD_X86_PAGE_TRBYTES and a bitmap of the covered bytes, so a
   microDOS store bumps the page generation only if it hits translated code */
static uint8_t *trbits[MD_X86_CODE_PAGE_COUNT];
static uint8_t trpool[BB_TR_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
static unsigned trpool_used;
static uint8_t want_flags[MD_X86_CODE_PAGE_COUNT];
static uint8_t tracked[MD_X86_CODE_PAGE_COUNT];     /* pages with any flag, in order */
static unsigned ntracked;
static int last_rc = -1;
#if BB_HAVE_TIMER
static struct repeating_timer slice_timer;
static bool slice_cb(struct repeating_timer *t) { (void)t; C.irq |= 1u; return true; }
#endif

B86_HOT static void to_b86(void)
{
    MdX86 *m = &R->cpu;
    for (unsigned i = 0; i < 8u; ++i) C.r[i] = m->r[i];
    b86_set_seg(&C, B86_ES, m->es);
    b86_set_seg(&C, B86_CS, m->cs);
    b86_set_seg(&C, B86_SS, m->ss);
    b86_set_seg(&C, B86_DS, m->ds);
    C.ip = m->ip;
    b86_set_flags(&C, md_x86_flags(m));
}

B86_HOT static void to_md(void)
{
    MdX86 *m = &R->cpu;
    for (unsigned i = 0; i < 8u; ++i) m->r[i] = (uint16_t)C.r[i];
    m->es = (uint16_t)C.seg[B86_ES];
    m->cs = (uint16_t)C.seg[B86_CS];
    m->ss = (uint16_t)C.seg[B86_SS];
    m->ds = (uint16_t)C.seg[B86_DS];
    m->ip = (uint16_t)C.ip;
    md_x86_set_flags(m, b86_get_flags(&C));
}

B86_HOT static void code_hook(B86Cpu *c, uint32_t lin, uint32_t len)
{
    (void)c;
#if MICRODOS_TRANSLATION_SUPPORT
    for (uint32_t a = lin, end = lin + len; a < end; ) {
        if (a >= MD_X86_ADDRESS_SPACE) return;        /* HMA: microDOS never writes there */
        unsigned p = a >> MD_X86_CODE_PAGE_SHIFT;
        uint32_t pend = ((uint32_t)p + 1u) << MD_X86_CODE_PAGE_SHIFT;
        uint32_t stop = end < pend ? end : pend;
        if (trbits[p] == NULL && !(want_flags[p] & MD_X86_PAGE_TRANSLATED)) {
            if (want_flags[p] == 0) tracked[ntracked++] = (uint8_t)p;
            if (trpool_used < BB_TR_PAGES) {
                trbits[p] = trpool[trpool_used++];
                memset(trbits[p], 0, MD_X86_CODE_PAGE_SIZE / 8u);
                want_flags[p] |= MD_X86_PAGE_TRBYTES;
            } else {
                want_flags[p] |= MD_X86_PAGE_TRANSLATED;  /* pool full: page-level */
            }
            R->code_page_executable[p] |= want_flags[p];
        }
        if (trbits[p]) {
            for (uint32_t b = a; b < stop; ++b) {
                uint32_t o = b & MD_X86_CODE_PAGE_MASK;
                trbits[p][o >> 3] |= (uint8_t)(1u << (o & 7u));
            }
        }
        a = stop;
    }
#else
    (void)lin; (void)len;
#endif
}

/* re-assert our page flags (cheap) in case microDOS rewrote the table */
B86_HOT static void track_pages(void)
{
#if MICRODOS_TRANSLATION_SUPPORT
    for (unsigned i = 0; i < ntracked; ++i) {
        const unsigned p = tracked[i];
        R->code_page_executable[p] |= want_flags[p];
    }
    R->cpu.tr_live_bits = trbits;
#endif
}

B86_HOT static void sync_pages(void)
{
#if MICRODOS_TRANSLATION_SUPPORT
    for (unsigned i = 0; i < ntracked; ++i) {
        const unsigned p = tracked[i];
        const uint32_t g = R->code_page_generation[p];
        if (g != gen_seen[p]) {
            gen_seen[p] = g;
            uint32_t k = b86_jit_sync_external(J, p << MD_X86_CODE_PAGE_SHIFT, MD_X86_CODE_PAGE_SIZE);
            ++st.page_syncs;
            st.page_invalidations += k;
#ifdef BB_DEBUG
            if (k) fprintf(stderr, "[bb]   page %02X: %u code lines changed at %04X:%04X\n", p, k, R->cpu.cs, R->cpu.ip);
#endif
        }
    }
#endif
}

/* Bounded diagnostics: declarations before B86_HOT function sections. */
static uint32_t bb_trace_ints, bb_trace_in201, bb_trace_in3da, bb_trace_runs;
/* Read-only handoff recorder. No guest state changes. */
static uint32_t bb_handoff_n, bb_interp_skips, bb_post_video_slices;
static uint8_t bb_video_seen;
static int bb_log_n(uint32_t n) { return n <= 16u || (n & (n-1u)) == 0u; }
/* A20 ON: 1088 KiB guest buffer, not the legacy 1 MiB wrap used by v5. */
#define BB_V6_GUEST_BYTES 0x110000u
static uint32_t bb_v6_linear(uint16_t seg, uint16_t off) {
    return ((uint32_t)seg << 4) + (uint32_t)off;
}
static uint8_t bb_v6_byte(uint32_t addr) {
    return R && R->cpu.memory && addr < BB_V6_GUEST_BYTES ? R->cpu.memory[addr] : 0;
}
static void bb_v6_report(const char *tag, uint16_t cs, uint16_t ip,
                         uint16_t ss, uint16_t sp, uint16_t ax,
                         uint16_t ds, uint16_t es, uint16_t flags,
                         int rc, uint32_t retired) {
    uint32_t pc=bb_v6_linear(cs,ip), stk=bb_v6_linear(ss,sp);
    printf("[bb-v6] %s event=%lu cs:ip=%04X:%04X linear=%05lX "
           "ss:sp=%04X:%04X stack=%05lX ax=%04X ds=%04X es=%04X "
           "flags=%04X rc=%d retired=%lu code=",
           tag,(unsigned long)++bb_handoff_n,(unsigned)cs,(unsigned)ip,
           (unsigned long)pc,(unsigned)ss,(unsigned)sp,(unsigned long)stk,
           (unsigned)ax,(unsigned)ds,(unsigned)es,(unsigned)flags,
           rc,(unsigned long)retired);
    for(unsigned i=0;i<12;i++) printf("%02X",bb_v6_byte(pc+i));
    printf(" stack=");
    for(unsigned i=0;i<16;i++) printf("%02X",bb_v6_byte(stk+i));
    printf(" region=%s\n",pc>=BB_V6_GUEST_BYTES?"OUT-OF-GUEST":
           pc>=0x100000u?"HMA":pc>=0xA0000u?"ROM-VIDEO":"DOS");
    fflush(stdout);
}
static void bb_cpu_snapshot(const char *tag, const B86Cpu *c, int rc, uint32_t insns) {
    bb_v6_report(tag,(uint16_t)c->seg[B86_CS],(uint16_t)c->ip,
        (uint16_t)c->seg[B86_SS],(uint16_t)c->r[B86_SP],
        (uint16_t)c->r[B86_AX],(uint16_t)c->seg[B86_DS],
        (uint16_t)c->seg[B86_ES],b86_get_flags((B86Cpu*)c),rc,insns);
}
/* Called only from the generated microDOS interpreter fallback. No mutation. */
void bb_live_trace_interpreter(MdRuntime *rt, const char *phase, uint64_t before) {
    static uint32_t calls;
    if (!bb_video_seen || !rt || rt!=R) return;
    (void)phase; (void)before; (void)calls;
    return; /* v19: first-invalid guard records each interpreter exit separately. */
    uint32_t n=++calls;
    uint32_t pc=bb_v6_linear(rt->cpu.cs,rt->cpu.ip);
    /* Always report the first handoffs, HMA, or out-of-guest transitions;
       powers of two thereafter cap serial overhead during prolonged loops. */
    if(n<=48u || bb_log_n(n) || (pc>=0x100000u && n<=192u)) {
        bb_v6_report(phase,rt->cpu.cs,rt->cpu.ip,rt->cpu.ss,
            rt->cpu.r[4],rt->cpu.r[0],rt->cpu.ds,rt->cpu.es,
            md_x86_flags(&rt->cpu),0,(uint32_t)(rt->instructions-before));
    }
}

/* V7: compact handoff ring. This records boundary states, not every x86 instruction. */
#define BB_V7_RING 128u
typedef struct {
    uint16_t cs,ip,ss,sp,ax,ds,es,flags;
    uint32_t linear;
    uint8_t code[8], stack[12];
    uint8_t kind;
    uint32_t retired;
} BbV7Rec;
#ifndef __uninitialized_psram
#define __uninitialized_psram(name)   /* host builds: ordinary .bss */
#endif
static BbV7Rec __uninitialized_psram("bb_v7") bb_v7_ring[BB_V7_RING];   /* v46: debug ring in PSRAM */
static unsigned bb_v7_write,bb_v7_count;
static int bb_v7_captured;
static int bb_v10_ivt_seen;
static uint32_t bb_v10_small_dispatches;
static void bb_v7_record(unsigned kind,uint16_t cs,uint16_t ip,uint16_t ss,uint16_t sp,
                         uint16_t ax,uint16_t ds,uint16_t es,uint16_t flags,uint32_t ins) {
    BbV7Rec *p=&bb_v7_ring[bb_v7_write++%BB_V7_RING];
    uint32_t addr=bb_v6_linear(cs,ip), stack=bb_v6_linear(ss,sp);
    p->cs=cs;p->ip=ip;p->ss=ss;p->sp=sp;p->ax=ax;p->ds=ds;p->es=es;
    p->flags=flags;p->linear=addr;p->kind=(uint8_t)kind;p->retired=ins;
    for(unsigned j=0;j<8;j++)p->code[j]=bb_v6_byte(addr+j);
    for(unsigned j=0;j<12;j++)p->stack[j]=bb_v6_byte(stack+j);
    if(bb_v7_count<BB_V7_RING)++bb_v7_count;
}
static void bb_v7_dump(const char *reason) {
    printf("[bb-v10] SNAPSHOT reason=%s history=%u guest_bytes=%05X\n",reason,bb_v7_count,BB_V6_GUEST_BYTES);
    unsigned start=bb_v7_write-bb_v7_count;
    for(unsigned n=0;n<bb_v7_count;n++) {
        BbV7Rec *r=&bb_v7_ring[(start+n)%BB_V7_RING];
        printf("[bb-v10] %03u kind=%u %04X:%04X physical=%05lX ss:sp=%04X:%04X ax=%04X ds=%04X es=%04X flags=%04X retired=%lu code=",
               n,r->kind,r->cs,r->ip,(unsigned long)r->linear,r->ss,r->sp,r->ax,r->ds,r->es,r->flags,(unsigned long)r->retired);
        for(unsigned j=0;j<8;j++)printf("%02X",r->code[j]);
        printf(" stack=");for(unsigned j=0;j<12;j++)printf("%02X",r->stack[j]);
        printf("\n");
    }
    fflush(stdout);
}
/* V10 non-stopping anomalous transfer capture. Zero code by itself is legal
 * x86; this snapshot is evidence, never an execution rejection. */
static int bb_v7_check(MdRuntime *rt,const char *origin) {
    if(!bb_video_seen||bb_v7_captured||!rt||rt!=R)return 0;
    uint32_t pc=bb_v6_linear(rt->cpu.cs,rt->cpu.ip);
    if(pc>=BB_V6_GUEST_BYTES)return 0;
    /* Exclude the IVT/BDA and conventional program code. Trigger on the
       first zero-filled low-memory transition or HMA transition. */
    if(!((pc>=0x500u && pc<0x8000u) || pc>=0x100000u))return 0;
    for(unsigned j=0;j<8;j++)if(bb_v6_byte(pc+j)!=0)return 0;
    bb_v7_captured=1;
    bb_v7_record(9,rt->cpu.cs,rt->cpu.ip,rt->cpu.ss,rt->cpu.r[4],rt->cpu.r[0],rt->cpu.ds,rt->cpu.es,md_x86_flags(&rt->cpu),0);
    printf("[bb-v10] FIRST-SUSPECT origin=%s cs:ip=%04X:%04X physical=%05lX no-stop=1\n",
           origin,rt->cpu.cs,rt->cpu.ip,(unsigned long)pc);
    bb_v7_dump(origin);
    return 0;
}

/* v17: first observable suspicious *execution boundary*, not a decoded
 * instruction. IVT bytes are data, and a zero-only code window may be valid,
 * so this is an intentionally strict diagnostic stop, not a production rule. */
static void bb_live_v21_dump(const MdRuntime *rt);
static int bb_v17_stopped;
static int bb_v17_guard(MdRuntime *rt, const char *origin,
                         uint16_t from_cs, uint16_t from_ip,
                         uint16_t from_ss, uint16_t from_sp,
                         uint32_t retired, int rc)
{
    if (!bb_video_seen || bb_v17_stopped || !rt || rt != R ||
        rt->stop_reason != MD_STOP_NONE) return 0;
    uint32_t pc=bb_v6_linear(rt->cpu.cs,rt->cpu.ip);
    int ivt=(pc < 0x400u);
    int zero=0;
    if (!ivt && ((pc>=0x500u && pc<0x8000u) || pc>=0x100000u)) {
        zero=1;
        for (unsigned j=0;j<8u;j++) if (bb_v6_byte(pc+j)) {zero=0;break;}
    }
    if (!ivt && !zero) return 0;
    bb_v17_stopped=1;
    bb_live_v21_dump(rt);
    printf("[bb-v17] FIRST-INVALID kind=%s origin=%s from=%04X:%04X ss:sp=%04X:%04X to=%04X:%04X physical=%05lX retired=%lu rc=%d\n",
           ivt?"IVT-EXEC":"ZERO-CODE",origin,from_cs,from_ip,from_ss,from_sp,
           rt->cpu.cs,rt->cpu.ip,(unsigned long)pc,(unsigned long)retired,rc);
    printf("[bb-v17] SOURCE code=");
    uint32_t source=bb_v6_linear(from_cs,from_ip);
    for(unsigned j=0;j<24u;j++)printf("%02X",bb_v6_byte(source+j));
    printf(" stack=");
    uint32_t stack=bb_v6_linear(from_ss,from_sp);
    for(unsigned j=0;j<24u;j++)printf("%02X",bb_v6_byte(stack+j));
    printf("\n[bb-v17] TARGET code=");
    for(unsigned j=0;j<24u;j++)printf("%02X",bb_v6_byte(pc+j));
    printf(" stack=");stack=bb_v6_linear(rt->cpu.ss,rt->cpu.r[4]);
    for(unsigned j=0;j<24u;j++)printf("%02X",bb_v6_byte(stack+j));
    printf("\n");
    bb_v7_dump("v17-first-invalid");
    rt->fault_linear=pc;
    rt->fault_opcode=bb_v6_byte(pc);
    rt->stop_reason=MD_STOP_FAULT;
    printf("[bb-v17] STOP diagnostic=1 reason=first-invalid-boundary NOTE=origin-instruction-not-yet-proven\n");
    fflush(stdout);
    return 1;
}
/* v21: continuous, bounded last-128 interpreter instruction history.
 * Each record is BEFORE its instruction; both source bytes and stack contents
 * are saved at execution time, not reconstructed from modified guest RAM. */
#define BB_V21_HISTORY 128u
typedef struct {
    uint16_t cs,ip,ss,sp,ax,bx,cx,dx,si,di,bp,ds,es,flags;
    uint8_t code[8],stack[12];
} BbV21Step;
static BbV21Step __uninitialized_psram("bb_v21") bb_v21_steps[BB_V21_HISTORY];   /* v46: PSRAM */
static uint32_t bb_v21_next,bb_v21_count;
static int bb_v21_active,bb_v21_dumped;
int bb_live_v21_enabled(const MdRuntime *rt) {
    if (!bb_video_seen || !rt || rt != R || bb_v17_stopped) return 0;
    return 0; /* v23: disable instruction-by-instruction diagnostic overhead */
    if (!bb_v21_active) {
        bb_v21_active=1;
        printf("[bb-v21] ROLLING-TRACE active=1 history=128 mode=interpreter-only\n");
        fflush(stdout);
    }
    return 1;
}
void bb_live_v21_before_step(const MdRuntime *rt) {
    if (!bb_v21_active || !rt || rt!=R || bb_v17_stopped) return;
    MdX86 *c=(MdX86 *)&rt->cpu;
    BbV21Step *h=&bb_v21_steps[bb_v21_next % BB_V21_HISTORY];
    h->cs=c->cs;h->ip=c->ip;h->ss=c->ss;h->sp=c->r[4];
    h->ax=c->r[0];h->bx=c->r[3];h->cx=c->r[1];h->dx=c->r[2];
    h->si=c->r[6];h->di=c->r[7];h->bp=c->r[5];
    h->ds=c->ds;h->es=c->es;h->flags=md_x86_flags(c);
    uint32_t pc=bb_v6_linear(h->cs,h->ip),sp=bb_v6_linear(h->ss,h->sp);
    for(unsigned j=0;j<8u;j++)h->code[j]=bb_v6_byte(pc+j);
    for(unsigned j=0;j<12u;j++)h->stack[j]=bb_v6_byte(sp+j);
    ++bb_v21_next;if(bb_v21_count<BB_V21_HISTORY)++bb_v21_count;
}
static void bb_live_v21_dump(const MdRuntime *rt) {
    if (bb_v21_dumped) return;
    bb_v21_dumped=1;
    printf("[bb-v21] HISTORY count=%lu saved-before-instruction chronological=1\n",(unsigned long)bb_v21_count);
    uint32_t first=bb_v21_next-bb_v21_count;
    for(uint32_t i=0;i<bb_v21_count;i++) {
        BbV21Step *h=&bb_v21_steps[(first+i)%BB_V21_HISTORY];
        printf("[bb-v21] STEP age=%ld cs:ip=%04X:%04X ax=%04X bx=%04X cx=%04X dx=%04X si=%04X di=%04X bp=%04X ds=%04X es=%04X ss:sp=%04X:%04X flags=%04X code=",
          (long)i-(long)bb_v21_count,h->cs,h->ip,h->ax,h->bx,h->cx,h->dx,h->si,h->di,h->bp,h->ds,h->es,h->ss,h->sp,h->flags);
        for(unsigned j=0;j<8;j++)printf("%02X",h->code[j]);
        printf(" stack=");for(unsigned j=0;j<12;j++)printf("%02X",h->stack[j]);printf("\n");
    }
    if(rt) {
        printf("[bb-v21] DEST cs:ip=%04X:%04X ss:sp=%04X:%04X flags=%04X\n",
          rt->cpu.cs,rt->cpu.ip,rt->cpu.ss,rt->cpu.r[4],md_x86_flags((MdX86*)&rt->cpu));
    }
    printf("[bb-v21] IVT-0 0000:0000=");
    for(unsigned j=0;j<16;j++)printf("%02X",bb_v6_byte(j));
    printf(" IVT-10 0000:0040=");
    for(unsigned j=0;j<16;j++)printf("%02X",bb_v6_byte(0x40u+j));
    printf(" IVT-16 0000:0058=");
    for(unsigned j=0;j<16;j++)printf("%02X",bb_v6_byte(0x58u+j));
    printf("\n");fflush(stdout);
}
int bb_live_v21_after_step(MdRuntime *rt) {
    if (!bb_v21_active || !rt || rt!=R || bb_v17_stopped) return 0;
    uint16_t cs=0,ip=0,ss=0,sp=0;
    if(bb_v21_count) {
        const BbV21Step *h=&bb_v21_steps[(bb_v21_next-1u)%BB_V21_HISTORY];
        cs=h->cs;ip=h->ip;ss=h->ss;sp=h->sp;
    }
    return bb_v17_guard(rt,"interp-step",cs,ip,ss,sp,1u,0);
}

static uint64_t bb_v24_interp_calls;
static uint64_t bb_v24_interp_insns;
static uint16_t bb_v17_interp_cs,bb_v17_interp_ip,bb_v17_interp_ss,bb_v17_interp_sp;
void bb_live_v17_interp_begin(MdRuntime *rt) {
    if (!rt) return;
    bb_v17_interp_cs=rt->cpu.cs;bb_v17_interp_ip=rt->cpu.ip;
    bb_v17_interp_ss=rt->cpu.ss;bb_v17_interp_sp=rt->cpu.r[4];
}
void bb_live_v7_after_interpreter(MdRuntime *rt,const char *origin,uint64_t before) {
    if(!bb_video_seen||!rt||rt!=R)return;
    static uint32_t v19_interpreter_exits;
    ++v19_interpreter_exits;
    ++bb_v24_interp_calls;
    bb_v24_interp_insns += rt->instructions-before;
    /* This callback observes completed interpreter slices; its wall-time is
       accounted separately by the guest loop, not measurable here. */

    if (0) {
        printf("[bb-v19] INTERP-PROGRESS exit=%lu retired=%lu cs:ip=%04X:%04X ss:sp=%04X:%04X\n",
            (unsigned long)v19_interpreter_exits,(unsigned long)(rt->instructions-before),
            rt->cpu.cs,rt->cpu.ip,rt->cpu.ss,rt->cpu.r[4]);
        fflush(stdout);
    }
    bb_v7_record(4,rt->cpu.cs,rt->cpu.ip,rt->cpu.ss,rt->cpu.r[4],rt->cpu.r[0],rt->cpu.ds,rt->cpu.es,md_x86_flags(&rt->cpu),(uint32_t)(rt->instructions-before));
    if (bb_v17_guard(rt,origin,bb_v17_interp_cs,bb_v17_interp_ip,
                     bb_v17_interp_ss,bb_v17_interp_sp,
                     (uint32_t)(rt->instructions-before),0)) return;
    (void)bb_v7_check(rt,origin);
}

static void bb_trace_port(uint16_t port, uint8_t result, uint32_t n) {
    if (n<=8u || (n<=4096u && (n&(n-1u))==0u)) {
        printf("[bb-trace] IN %04X n=%lu value=%02X cs:ip=%04X:%04X\n",(unsigned)port,
               (unsigned long)n,(unsigned)result,(unsigned)C.seg[B86_CS],(unsigned)C.ip);
        fflush(stdout);
    }
}
/* v22: BIOS keyboard services, shared between native and interpreter.
 * Queue uses conventional PC BIOS Data Area 0040:001A/001C and 001E..003D.
 * No synthetic keypresses. No-key AH=00 retries the INT later.
 * A platform keyboard producer may append BIOS AX words to that BDA ring.
 */
static unsigned bb_v22_key_calls;
static uint16_t bb_v22_word(const uint8_t *m, unsigned addr)
{ return (uint16_t)((unsigned)m[addr] | ((unsigned)m[addr+1u]<<8)); }
static void bb_v22_write_word(uint8_t *m, unsigned addr, uint16_t w)
{ m[addr]=(uint8_t)w; m[addr+1u]=(uint8_t)(w>>8); }
static void bb_v22_queue_init(uint8_t *m)
{
    uint16_t h=bb_v22_word(m,0x41au),t=bb_v22_word(m,0x41cu);
    if (h<0x1eu || h>=0x3eu || (h&1u) || t<0x1eu || t>=0x3eu || (t&1u)) {
        bb_v22_write_word(m,0x41au,0x1eu);
        bb_v22_write_word(m,0x41cu,0x1eu);
    }
}
/* v23: USB CDC input -> standard BIOS keyboard ring after video starts.
 * The DOS command reader owns console input before mode 13h.
 * This is a minimal ASCII-to-set-1 mapping; extended keys need a later pass. */
static uint32_t bb_v23_keys,bb_v23_key_drop,bb_v23_polls;
static uint32_t bb_v23_lcd_ticks,bb_v23_changed_samples,bb_v23_last_hash;
/* v24: additive counters; do not alter guest semantics. */
static uint64_t bb_v24_start_us,bb_v24_jit_us,bb_v24_lcd_us,bb_v24_hash_us;
static uint64_t bb_v24_jit_calls,bb_v24_zero,bb_v24_zero_trap,bb_v24_jit_insns;
static uint64_t bb_v24_lcd_calls,bb_v24_hash_calls,bb_v24_interp_us;
static uint32_t bb_v24_start_bda_tick,bb_v24_last_bda_tick;
static uint64_t bb_v25_last_lcd_us;
static uint64_t bb_v25_lcd_skipped;
static uint32_t bb_v25_timer_updates;

/* v33: blitz86 counters as deltas since the previous line (periodic and Ctrl+]) */
static void bb_v33_jit_line(void) {
    static B86JitStats prev;
    static uint64_t prev_native, prev_xa, prev_xm, prev_nm;
    uint64_t xa=bb_xip_accesses(), xm=bb_xip_misses();
    if(!J)return;
    const B86JitStats *s=b86_jit_stats(J);
    printf("[bb-jit] native-ms=%llu translate-ms=%llu flushes=%llu blocks=%llu cold-insns=%llu "
           "rt-step=%llu rt-cond=%llu rt-flags=%llu rt-light=%llu rt-smc=%llu rt-rep=%llu "
           "joins=%llu inner=%llu splits=%llu xip-access=%llu xip-miss=%llu native-miss=%llu\n",
        (unsigned long long)((st.native_us-prev_native)/1000u),
        (unsigned long long)((s->translate_us-prev.translate_us)/1000u),
        (unsigned long long)(s->flushes-prev.flushes),(unsigned long long)(s->blocks-prev.blocks),
        (unsigned long long)(s->cold_insns-prev.cold_insns),
        (unsigned long long)(s->rt_step-prev.rt_step),(unsigned long long)(s->rt_cond-prev.rt_cond),
        (unsigned long long)(s->rt_flags-prev.rt_flags),(unsigned long long)(s->rt_light-prev.rt_light),
        (unsigned long long)(s->rt_smc-prev.rt_smc),(unsigned long long)(s->rt_rep-prev.rt_rep),
        (unsigned long long)(s->joins-prev.joins),(unsigned long long)(s->inner_branches-prev.inner_branches),
        (unsigned long long)(s->splits-prev.splits),
        (unsigned long long)(xa-prev_xa),(unsigned long long)(xm-prev_xm),
        (unsigned long long)(st.native_misses-prev_nm));
    prev=*s; prev_native=st.native_us; prev_xa=xa; prev_xm=xm; prev_nm=st.native_misses;
    fflush(stdout);
}
static void bb_v24_report(void);
/* v51: a report is ~60 lines; over USB CDC each printf may block while the
 * host drains, so a burst of Ctrl+] presses could run past the 3 s hang
 * watchdog (VGA mode) and reset the board mid-run. Pause the watchdog for
 * the report and ignore presses closer than 1 s apart. */
static void bb_diag_pause(int pause);
static void bb_time_freeze(uint64_t us);
static void bb_v33_stats_now(void)
{
    static uint64_t last_us;
    uint64_t now = bb_now_us();
    if (last_us && now - last_us < 1000000u) return;
    bb_diag_pause(1);
    bb_v24_report();
    fflush(stdout);
    bb_diag_pause(0);
    last_us = bb_now_us();
    /* v51c: the guest is frozen while the report prints (tens to hundreds of
       ms over USB). Take that time out of every guest-visible clock, or the
       BIOS tick jumps and PIT interrupts get coalesced, which throws off
       3DBENCH's time-based animation (black 3D view) and its fps result. */
    bb_time_freeze(last_us - now);
}
static uint32_t bb_v24_bda_tick(void); /* v34 diagnostic declaration */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
static uint32_t bb_v51_stack_peak(void);
#endif
static void bb_v24_report(void) {
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    printf("[bb-v51-stack] core0 peak=%lu of %lu bytes\n", (unsigned long)bb_v51_stack_peak(),
           (unsigned long)((uintptr_t)__StackTop - (uintptr_t)__StackBottom));
#endif
    if(!R||!bb_video_seen)return;
    uint64_t elapsed=bb_now_us()-bb_v24_start_us;
    printf("[bb-v24] PROFILE wall-ms=%llu jit-calls=%llu jit-zero=%llu zero-trap=%llu jit-insns=%llu jit-ms=%llu interp-calls=%llu interp-insns=%llu interp-ms=%llu lcd-tick-calls=%llu lcd-tick-ms=%llu hash-calls=%llu hash-ms=%llu bda-tick-start=%lu bda-tick-now=%lu\n",
       (unsigned long long)(elapsed/1000u),(unsigned long long)bb_v24_jit_calls,
       (unsigned long long)bb_v24_zero,(unsigned long long)bb_v24_zero_trap,
       (unsigned long long)bb_v24_jit_insns,(unsigned long long)(bb_v24_jit_us/1000u),
       (unsigned long long)bb_v24_interp_calls,(unsigned long long)bb_v24_interp_insns,
       (unsigned long long)(bb_v24_interp_us/1000u),(unsigned long long)bb_v24_lcd_calls,
       (unsigned long long)(bb_v24_lcd_us/1000u),(unsigned long long)bb_v24_hash_calls,
       (unsigned long long)(bb_v24_hash_us/1000u),(unsigned long)bb_v24_start_bda_tick,
       (unsigned long)bb_v24_last_bda_tick);
    printf("[bb-v25] RECOVERY lcd-skipped=%llu lcd-calls=%llu timer-updates=%lu hz=18.2065 refresh-cap=60 hash-disabled=1\n",
       (unsigned long long)bb_v25_lcd_skipped,
       (unsigned long long)bb_v24_lcd_calls,
       (unsigned long)bb_v25_timer_updates);
    bb_v33_jit_line();
    b86_jit_hot_report(J);
    bb_pit_report();
    bb_irq36_report();
#ifdef BB_V49_PC_PROFILE
    bb49_report(J);
#endif
    /* v34: read the actual guest-visible BIOS tick field, not the
       previously sampled bb_v24_last_bda_tick.  This is telemetry only. */
    {
        const uint32_t now_tick=bb_v24_bda_tick();
        const uint32_t expected=(uint32_t)
            ((bb_v24_start_bda_tick + elapsed / 54925ull) % 0x1800b0ull);
        const int32_t delta=(int32_t)now_tick-(int32_t)expected;
        printf("[bb-v34-clock] wall-ms=%llu bda-now=%lu expected=%lu delta-ticks=%ld\n",
               (unsigned long long)(elapsed/1000ull),
               (unsigned long)now_tick,(unsigned long)expected,(long)delta);
    }
}
static uint32_t bb_v24_bda_tick(void) {
    if(!R)return 0;
    const uint8_t *m=R->cpu.memory;
    return (uint32_t)m[0x46c] | ((uint32_t)m[0x46d]<<8) |
           ((uint32_t)m[0x46e]<<16) | ((uint32_t)m[0x46f]<<24);
}

/* v25: real-time BIOS tick maintenance and LCD refresh pacing. */
static void bb_v25_bios_time(void) {
    if (!R || !bb_video_seen || !bb_v24_start_us) return;
    /* 18.2065Hz BIOS tick from monotonic host time, independent of guest
       execution throughput. 54925 microseconds is the rounded PC tick. */
    uint64_t elapsed = bb_now_us() - bb_v24_start_us;
    uint32_t ticks = (uint32_t)(elapsed / 54925ull);
    if (ticks >= 0x1800b0u) ticks %= 0x1800b0u;
    uint8_t *m = R->cpu.memory;
    uint32_t old = (uint32_t)m[0x46cu] | ((uint32_t)m[0x46du]<<8) |
                   ((uint32_t)m[0x46eu]<<16) | ((uint32_t)m[0x46fu]<<24);
    if (ticks != old) {
        m[0x46cu]=(uint8_t)ticks;
        m[0x46du]=(uint8_t)(ticks>>8);
        m[0x46eu]=(uint8_t)(ticks>>16);
        m[0x46fu]=(uint8_t)(ticks>>24);
        ++bb_v25_timer_updates;
    }
}
static uint8_t bb_v23_have_hash;
static uint8_t bb_v23_scan(unsigned c) {
    static const char letters[]="abcdefghijklmnopqrstuvwxyz";
    static const uint8_t scans[]={0x1e,0x30,0x2e,0x20,0x12,0x21,0x22,0x23,0x17,0x24,0x25,0x26,0x32,0x31,0x18,0x19,0x10,0x13,0x1f,0x14,0x16,0x2f,0x11,0x2d,0x15,0x2c};
    static const uint8_t digits[]={0x0b,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0a};
    unsigned lo=c|0x20u;
    for(unsigned i=0;i<26;i++) if(lo==(unsigned)letters[i])return scans[i];
    if(c>='0'&&c<='9')return digits[c-'0'];
    if(c==13||c==10)return 0x1c;
    if(c==27)return 0x01;
    if(c==8||c==127)return 0x0e;
    if(c==' ')return 0x39;
    return 0u;
}
static void bb_v23_enqueue_ascii(uint8_t *m,unsigned c) {
    if(c==10u)c=13u;
    if(c==127u)c=8u;
    if(c>127u)return;
    bb_v22_queue_init(m);
    uint16_t head=bb_v22_word(m,0x41au),tail=bb_v22_word(m,0x41cu);
    uint16_t next=(uint16_t)(tail+2u);
    if(next>=0x3eu)next=0x1eu;
    if(next==head){++bb_v23_key_drop;return;}
    bb_v22_write_word(m,0x400u+tail,(uint16_t)(((uint16_t)bb_v23_scan(c)<<8)|c));
    bb_v22_write_word(m,0x41cu,next);
    ++bb_v23_keys;
    printf("[bb-v23] KEY ascii=%02X scan=%02X queued=%lu\n",c,bb_v23_scan(c),(unsigned long)bb_v23_keys);
}
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
/* v39a: PSRAM miss calibration, on demand (Ctrl+T) instead of at boot.
   Uses the 64 KiB above 1 MiB of the guest buffer (unused by DOS 2.0);
   contents are read and written back unchanged. */
static void bb_v39_psram_calibrate(void)
{
    if (!R) return;
    volatile uint8_t *p = R->cpu.memory + 0x100000u;
    uint32_t sum = 0;
    for (unsigned i = 0; i < 65536u; i += 8u) sum += p[i];
    uint64_t t0 = time_us_64();
    for (unsigned r = 0; r < 4u; ++r) for (unsigned i = 0; i < 65536u; i += 8u) sum += p[i];
    uint64_t t1 = time_us_64();
    for (unsigned r = 0; r < 4u; ++r) for (unsigned i = 0; i < 65536u; i += 8u) p[i] = p[i];
    uint64_t t2 = time_us_64();
    printf("[bb-v38-psram] read-miss=%lu ns rmw-miss=%lu ns (per 8-byte line, 32768 lines each; sum=%lu)\n",
           (unsigned long)((t1 - t0) * 1000u / 32768u), (unsigned long)((t2 - t1) * 1000u / 32768u), (unsigned long)sum);
    fflush(stdout);
}
#endif
static void bb_v33_stats_now(void);
static void bb_v23_poll_input(void) {
    if(!bb_video_seen||!R)return;
    ++bb_v23_polls;
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    /* Avoid draining multiple characters during a single guest slice. */
    int c=getchar_timeout_us(0);
    /* v33: once video owns the console, this poll is the only reader of the
       serial port, so Ctrl+] (0x1D) is handled here instead of reaching the
       guest keyboard queue. */
    if(c==0x1D){bb_v33_stats_now();return;}
    if(c==0x14){bb_v39_psram_calibrate();return;}   /* v39a: Ctrl+T */
    if(c==0x10){                      /* v38: Ctrl+P toggles the LCD presenter */
        extern volatile uint32_t bb_lcd_paused;
        bb_lcd_paused^=1u;
        bb_v33_stats_now();           /* interval boundary for the A/B comparison */
        printf("[bb-v38] LCD presenter %s (Ctrl+P toggles)\n",bb_lcd_paused?"PAUSED":"running");
        fflush(stdout);
        return;
    }
    if(c>=0)bb_v23_enqueue_ascii(R->cpu.memory,(unsigned)c);
#endif
}
static void bb_v23_graphics_sample(void) {
    /* v25: intentionally no full-frame/stride framebuffer hashing. */
    ++bb_v23_lcd_ticks;
}
static int bb_v22_keyboard(uint8_t *m, uint16_t *ax, uint16_t *flags,
                            uint16_t *ip, uint8_t *rewind)
{
    uint8_t ah=(uint8_t)(*ax>>8);
    uint16_t head,tail;
    if (ah!=0x00u && ah!=0x01u && ah!=0x02u && ah!=0x10u && ah!=0x11u && ah!=0x12u) return 0;
    bb_v23_poll_input();
    bb_v22_queue_init(m);
    head=bb_v22_word(m,0x41au);tail=bb_v22_word(m,0x41cu);
    if (ah==0x02u || ah==0x12u) {
        *ax=(uint16_t)((*ax&0xff00u)|m[0x417u]);
    } else if (head==tail) {
        if (ah==0x01u || ah==0x11u) *flags |= 0x0040u; /* ZF=1, preserve AX */
        else {
            /* Blocking read without inventing a key.  The guest reexecutes
             * INT 16h on the next quantum while host input may be polled. */
            *ip=(uint16_t)(*ip-2u); *rewind=1u;
        }
    } else {
        *ax=bb_v22_word(m,0x400u+head);
        *flags &= (uint16_t)~0x0040u;
        if (ah==0x00u || ah==0x10u) {
            uint16_t next=(uint16_t)(head+2u);
            bb_v22_write_word(m,0x41au,next>=0x3eu?0x1eu:next);
        }
    }
    if ((++bb_v22_key_calls)<=2u) {
        printf("[bb-v22] INT16 ah=%02X ax=%04X zf=%u head=%04X tail=%04X wait=%u\n",
            (unsigned)ah,(unsigned)*ax,(unsigned)((*flags>>6)&1u),head,tail,(unsigned)*rewind);
        fflush(stdout);
    }
    return 1;
}


/* ------------------------------------------------------------------------ */
/* v40: SRAM-backed guest pages (blitz86 -DB86_PAGED)                        */
/*                                                                          */
/* 3DBENCH streams two 64 KiB frame buffers through the 16 KiB XIP cache    */
/* every frame (~90% of core 0's PSRAM misses; a written line costs ~650    */
/* ns). blitz86 can move 4 KiB guest pages to SRAM; blitzBUS chooses:       */
/*  - VGA: A000:0000-FFFF while mode 13h is active. bb_vga and the LCD      */
/*    presenter read the SRAM copy, so core 1 stops reading PSRAM too.      */
/*  - "bbuf": the 16 consecutive conventional-memory pages with the most    */
/*    REP STOS/MOVS store traffic (a program's back buffer), re-evaluated   */
/*    about once a second.                                                  */
/* Coherence: microDOS reads/writes guest memory directly, so the bbuf      */
/* window is copied back before any call into microDOS (HLE interrupts,     */
/* BIOS-segment slices) and re-chosen later. The VGA window is not: DOS     */
/* I/O straight into A000 is not supported while it is mapped.             */
/* Known limit (accepted): a 16-bit access straddling a window's first or   */
/* last byte is not exact (frames carry a guard byte so it cannot overwrite */
/* SRAM).                                                                    */
/* ------------------------------------------------------------------------ */
#ifndef BB_PAGED_SRAM
#define BB_PAGED_SRAM 1
#endif
#define BB_WIN_BYTES 0x10000u
#define BB_WIN_PAGES (BB_WIN_BYTES >> 12)
#ifndef BB_BBUF_MIN_BYTES
#define BB_BBUF_MIN_BYTES (128u * 1024u)    /* REP bytes per 250 ms evaluation to bother */
#endif
#if defined(B86_PAGED) && BB_PAGED_SRAM
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
static uint8_t bb_vram[BB_WIN_BYTES + 4u] __attribute__((aligned(4096)));
#else   /* host harness: frames where their SMC-table index is clear of guest lines (as on the Pico) */
static uint8_t *bb_host_frames(void) { static uint8_t *f; if (!f) f = (uint8_t *)aligned_alloc(0x200000, 0x200000); return f; }
#define bb_vram (bb_host_frames() + 0x10000u)
#endif
#ifndef BB_BBUF_SRAM
#define BB_BBUF_SRAM 1       /* v46: on again (blitz86 (n) moved ~56 KiB of translator to flash) */
#endif
#if BB_BBUF_SRAM
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
static uint8_t bb_bbuf[BB_WIN_BYTES + 4u] __attribute__((aligned(4096)));
#else
#define bb_bbuf (bb_host_frames() + 0x30000u)
#endif
#endif
static int bb_vram_mapped;
static uint32_t bb_bbuf_lin;              /* 0: not mapped */
static unsigned bb_bbuf_cooldown;
static uint64_t bb_v40_maps, bb_v40_unmaps, bb_v40_vga_maps;
static uint32_t bb_v40_slices;

static volatile int bb_v40_vga_pending;
static void bb_v40_vga_sync(void)
{
    if (!J) return;
    int want = bb_vga_active();
    if (want && !bb_vram_mapped) {
        int mr = b86_map_range(&C, 0xA0000u, BB_WIN_BYTES, bb_vram);
        if (mr == 0) {
            bb_vram_mapped = 1; ++bb_v40_vga_maps;
            bb_vga_set_vram(bb_vram);
            printf("[bb-v40-paged] A000 window -> SRAM %p\n", (void *)bb_vram); fflush(stdout);
        } else {
            printf("[bb-v40-paged] A000 window NOT mapped (rc=%d)\n", mr); fflush(stdout);
            bb_vram_mapped = -1;              /* do not retry every INT 10h */
        }
    } else if (!want && bb_vram_mapped == 1) {
        bb_vga_set_vram(NULL);
        b86_unmap_range(&C, 0xA0000u, BB_WIN_BYTES);
        bb_vram_mapped = 0;
        printf("[bb-v40-paged] A000 window back to PSRAM\n"); fflush(stdout);
    }
}
/* before microDOS touches guest memory */
static void bb_v40_release(const char *why)
{
    if (!bb_bbuf_lin) return;
    b86_unmap_range(&C, bb_bbuf_lin, BB_WIN_BYTES);
    ++bb_v40_unmaps;
    if (bb_v40_unmaps <= 8u) { printf("[bb-v40-paged] bbuf %05lX back to PSRAM (%s)\n", (unsigned long)bb_bbuf_lin, why); fflush(stdout); }
    bb_bbuf_lin = 0;
    bb_bbuf_cooldown = 2u;
}
/* once per ~1024 native slices: pick the hottest REP-store window */
static void bb_v40_tick(void)
{
#if !BB_BBUF_SRAM
    return;
#endif
    /* v47: evaluate on a wall-clock period, not every 1024 slices (slice
       lengths vary a lot; the slice clock could miss the benchmark) */
    static uint64_t bb_v40_last_us;
    if (!J) return;
    uint64_t now = bb_now_us();
    if (now - bb_v40_last_us < 250000u) return;
    bb_v40_last_us = now; ++bb_v40_slices;
    uint32_t *cnt = C.rep_page_bytes;
    /* blitz86 does not translate stack (SS) accesses: no mapped page may lie
       in the current SS window */
    uint32_t ss_lo = C.seg[B86_SS] << 4, ss_hi = ss_lo + 0x10000u;
    if (bb_bbuf_lin && bb_bbuf_lin < ss_hi && bb_bbuf_lin + BB_WIN_BYTES > ss_lo) bb_v40_release("stack moved into window");
    if (bb_bbuf_cooldown) { --bb_bbuf_cooldown; memset(cnt, 0, sizeof C.rep_page_bytes); return; }
    if (!bb_bbuf_lin) {
        /* best 16-page windows by REP store bytes; try them in order, since a
           window holding translated code (or a bad frame) is refused */
        const unsigned lo = 0x10000u >> 12, hi = 0xA0000u >> 12;     /* skip DOS, stop below VGA */
        unsigned tried[8]; unsigned ntried = 0;
        for (unsigned attempt = 0; attempt < 8u && !bb_bbuf_lin; ++attempt) {
            uint64_t best = 0; unsigned bs = 0;
            for (unsigned p = lo; p + BB_WIN_PAGES <= hi; ++p) {
                uint32_t wl = p << 12;
                if (wl < ss_hi && wl + BB_WIN_BYTES > ss_lo) continue;
                int seen = 0;
                for (unsigned t = 0; t < ntried; ++t) seen |= tried[t] == p;
                if (seen) continue;
                uint64_t sum = 0;
                for (unsigned q = p; q < p + BB_WIN_PAGES; ++q) sum += cnt[q];
                if (sum > best) { best = sum; bs = p; }
            }
            if (best < BB_BBUF_MIN_BYTES) break;
            tried[ntried++] = bs;
            uint32_t lin = bs << 12;
#if BB_BBUF_SRAM
            int mr = b86_map_range(&C, lin, BB_WIN_BYTES, bb_bbuf);
            if (mr == 0) {
                bb_bbuf_lin = lin; ++bb_v40_maps;
                if (bb_v40_maps <= 8u) { printf("[bb-v40-paged] bbuf %05lX-%05lX -> SRAM (%llu REP bytes)\n", (unsigned long)lin, (unsigned long)(lin + BB_WIN_BYTES - 1u), (unsigned long long)best); fflush(stdout); }
            } else {
                static unsigned fails;
                if (++fails <= 8u) { printf("[bb-v44-paged] bbuf %05lX map refused rc=%d (%s, frame %p)\n", (unsigned long)lin, mr,
                                           mr == -3 ? "translated code in window" : mr == -2 ? "frame index collides" : "other", (void *)bb_bbuf); fflush(stdout); }
            }
#else
            (void)lin;
#endif
        }
    }
    memset(cnt, 0, sizeof C.rep_page_bytes);
}
#else
static int bb_v40_vga_pending;
static void bb_v40_vga_sync(void) {}
static void bb_v40_release(const char *why) { (void)why; }
static void bb_v40_tick(void) {}
#endif

B86_HOT static int hook_int(B86Cpu *c, uint8_t v)
{
    if (v == 0x16u) {
        uint16_t ax=(uint16_t)c->r[B86_AX], flags=b86_get_flags(c);
        uint16_t ip=(uint16_t)c->ip; uint8_t rewind=0;
        if(bb_v22_keyboard(R->cpu.memory,&ax,&flags,&ip,&rewind)) {
            c->r[B86_AX]=ax; b86_set_flags(c,flags);
            if(rewind)c->ip=ip;
            ++st.hook_calls;
            return 1;
        }
    }
    if (v == 0x10u) {
        if (++bb_trace_ints<=24u) {
            printf("[bb-trace] INT10 enter n=%lu ax=%04X cs:ip=%04X:%04X sp=%04X\n",
                   (unsigned long)bb_trace_ints,(unsigned)c->r[B86_AX],
                   (unsigned)c->seg[B86_CS],(unsigned)c->ip,(unsigned)c->r[B86_SP]);
            fflush(stdout);
        }
        uint16_t ax=(uint16_t)c->r[B86_AX], bx=(uint16_t)c->r[B86_BX];
        uint16_t cx=(uint16_t)c->r[B86_CX], dx=(uint16_t)c->r[B86_DX];
        uint16_t f=b86_get_flags(c);
        uint16_t es=(uint16_t)c->seg[B86_ES], bp=(uint16_t)c->r[B86_BP];
        if (bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)) {
            if ((uint8_t)(ax >> 8) == 0u && (uint8_t)ax == 0x13u) {
                bb_video_seen=1u;
                bb_v24_start_us=bb_now_us();
                bb_v24_start_bda_tick=bb_v24_bda_tick();

                bb_handoff_n=0;
                printf("[bb-handoff] MODE13 hook-return convention: before returning 1\n");
                fflush(stdout);
            }
            c->r[B86_AX]=ax; c->r[B86_BX]=bx;
            c->r[B86_CX]=cx; c->r[B86_DX]=dx;
            c->r[B86_BP]=bp; b86_set_seg(c,B86_ES,es);
            b86_set_flags(c,f);
            bb_v40_vga_pending = 1;             /* v51: map/unmap A000 between slices, not inside a block */
            ++st.hook_calls;
            if(bb_video_seen)bb_v7_record(1,(uint16_t)c->seg[B86_CS],(uint16_t)c->ip,
                (uint16_t)c->seg[B86_SS],(uint16_t)c->r[B86_SP],(uint16_t)c->r[B86_AX],
                (uint16_t)c->seg[B86_DS],(uint16_t)c->seg[B86_ES],b86_get_flags(c),0);
            if (bb_trace_ints<=24u) {
                printf("[bb-trace] INT10 handled ax=%04X cs:ip=%04X:%04X sp=%04X\n",
                       (unsigned)ax,(unsigned)c->seg[B86_CS],(unsigned)c->ip,(unsigned)c->r[B86_SP]);
                fflush(stdout);
            }
            if (bb_video_seen && bb_trace_ints <= 12u) {
                ++bb_handoff_n;
                bb_cpu_snapshot("int10-return",c,-1,0);
            }
            return 1;
        }
    }
#ifdef BB_DEBUG
    fprintf(stderr, "[bb]   int %02X at %04X:%04X\n", v, (unsigned)c->seg[B86_CS], (unsigned)c->ip);
#endif
    if (R->hooks.interrupt == NULL) return 0;
    if (v == 0) { static unsigned n0; if (++n0 <= 3u) { printf("[bb-v46] INT 00 (divide error) n=%u at %04X:%04X ax=%04X dx=%04X\n", n0, (unsigned)c->seg[B86_CS], (unsigned)c->ip, (unsigned)c->r[B86_AX], (unsigned)c->r[B86_DX]); fflush(stdout); } }
#if defined(B86_PAGED) && BB_PAGED_SRAM
    /* v46: only the DOS 2 device-driver vector (0xF1: request packets and
       transfer buffers) makes microDOS touch guest memory; others (e.g. INT 00
       raised by 3DBENCH, the 0xF0 strategy call) leave the window alone */
    if (bb_bbuf_lin && v == 0xF1u) {
        static char why[32];
        snprintf(why, sizeof why, "microDOS INT %02X AH=%02X", v, (unsigned)((c->r[B86_AX] >> 8) & 0xFFu));
        bb_v40_release(why);
    }
#endif
    to_md();                                    /* c->ip = return address */
    if (!R->hooks.interrupt(R, v, R->hooks.user)) return 0;
    ++st.hook_calls;
    to_b86();
    sync_pages();
    if (R->stop_reason != MD_STOP_NONE) c->irq |= 1u;
    return 1;
}
B86_HOT static uint8_t hook_in(B86Cpu *c, uint16_t port)
{
    uint8_t result;
    if(bb_irq36_in(port,&result))return result;
    if(bb_pit_in(port,&result,bb_now_us(),(uint16_t)c->seg[B86_CS],(uint16_t)c->ip,1))return result;
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    if (bb_vga_port_in(port,&result,time_us_64())) {
        if(port==0x201u)bb_trace_port(port,result,++bb_trace_in201);
        if(port==0x3DAu)bb_trace_port(port,result,++bb_trace_in3da);
        return result;
    }
#else
    if (bb_vga_port_in(port,&result,bb_now_us())) return result;
#endif
    (void)c;
    return R->hooks.in8 ? R->hooks.in8(R, port, R->hooks.user) : 0xFFu;
}
B86_HOT static void hook_out(B86Cpu *c, uint16_t port, uint8_t v)
{
    if(bb_irq36_out(port,v))return;
    if(bb_pit_out(port,v,bb_now_us(),(uint16_t)c->seg[B86_CS],(uint16_t)c->ip,1))return;
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    if (bb_vga_port_out(port,v,time_us_64())) return;
#else
    if (bb_vga_port_out(port,v,bb_now_us())) return;
#endif
    (void)c;
    if (R->hooks.out8) R->hooks.out8(R, port, v, R->hooks.user);
}

/* v15: the interpreter and native sidecar share VGA INT 10h handling.
 * The runtime's original MS-DOS interrupt hook stays intact for every other
 * vector and for INT 10h subfunctions not implemented by bb_vga_int10.
 * md_interp_step has already advanced IP past CD 10 before invoking hooks.
 */
static MdPortIn8Hook bb_v35_original_in8;
static MdPortOut8Hook bb_v35_original_out8;
static uint8_t bb_v35_pit_in8(MdRuntime *rt,uint16_t port,void *user) {
    uint8_t v=0;
    if(bb_irq36_in(port,&v))return v;
    if(bb_pit_in(port,&v,bb_now_us(),rt->cpu.cs,rt->cpu.ip,0))return v;
    return bb_v35_original_in8?bb_v35_original_in8(rt,port,user):0xffu;
}
static void bb_v35_pit_out8(MdRuntime *rt,uint16_t port,uint8_t v,void *user) {
    if(bb_irq36_out(port,v))return;
    if(bb_pit_out(port,v,bb_now_us(),rt->cpu.cs,rt->cpu.ip,0))return;
    if(bb_v35_original_out8)bb_v35_original_out8(rt,port,v,user);
}
static MdInterruptHook bb_v15_original_interrupt;
static unsigned bb_v15_video_calls;
static bool bb_v15_interrupt(MdRuntime *rt, uint8_t vector, void *user)
{
    if (vector == 0x16u) {
        MdX86 *cpu=&rt->cpu;
        uint16_t ax=cpu->r[0],flags=md_x86_flags(cpu),ip=cpu->ip;
        uint8_t rewind=0;
        if (bb_v22_keyboard(cpu->memory,&ax,&flags,&ip,&rewind)) {
            cpu->r[0]=ax; md_x86_set_flags(cpu,flags);
            if(rewind)cpu->ip=ip;
            return true;
        }
    }
    if (vector == 0x10u) {
        MdX86 *cpu = &rt->cpu;
        uint16_t ax=cpu->r[0], bx=cpu->r[3];
        uint16_t cx=cpu->r[1], dx=cpu->r[2];
        uint16_t es=cpu->es, bp=cpu->r[5];
        uint16_t flags=md_x86_flags(cpu);
        if (bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)) {
            cpu->r[0]=ax; cpu->r[3]=bx;
            cpu->r[1]=cx; cpu->r[2]=dx;
            cpu->r[5]=bp; cpu->es=es;
            md_x86_set_flags(cpu,flags);
            ++bb_v15_video_calls;
            if (bb_v15_video_calls <= 24u) {
                printf("[bb-v15] INTERP-INT10 handled n=%u ax=%04X cs:ip=%04X:%04X sp=%04X\n",
                       bb_v15_video_calls,ax,cpu->cs,cpu->ip,cpu->r[4]);
                fflush(stdout);
            }
            return true;
        }
    }
    return bb_v15_original_interrupt ? bb_v15_original_interrupt(rt,vector,user) : false;
}

static int start(MdRuntime *rt)
{
    R = rt;
    if (rt->hooks.interrupt != md_msdos2_boot_interrupt || rt->hooks.user == NULL) { failed = 1; fail_reason = "not-msdos2-boot"; return 0; }
    if (((uintptr_t)rt->cpu.memory & 63u) != 0) { failed = 1; fail_reason = "guest-not-64-aligned"; return 0; }
    bios_seg = ((const MdMsdos2Boot *)rt->hooks.user)->bios_segment;
    bb_diag_boot_report();
    bb_vga_init(rt->cpu.memory);
    bb_pit_init(bb_now_us());
    bb_irq36_init(bb_now_us());
    b86_init(&C, rt->cpu.memory);      /* guest buffer >= B86_MEM_BYTES (A20-on model) */
    C.int_hook = hook_int;
    C.code_hook = code_hook;
    C.in8 = hook_in;
    C.out8 = hook_out;
#if defined(__linux__)
    bb_code = mmap(NULL, BB_CODE_BYTES, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (bb_code == MAP_FAILED) { failed = 1; fail_reason = "mmap"; return 0; }
#endif
    J = b86_jit_create_ex(&C, bb_code, BB_CODE_BYTES, bb_hot, sizeof bb_hot);
    if (J == NULL) { failed = 1; fail_reason = "jit-create"; return 0; }
#if defined(BB_V49_PC_PROFILE) && defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    bb49_init(clock_get_hz(clk_sys)/BB49_SAMPLE_HZ);
#endif
#if !(defined(PICO_ON_DEVICE) && PICO_ON_DEVICE)
    bb_shadow = aligned_alloc(64, (B86_MEM_BYTES + 63u) & ~63u);
#endif
    if (bb_shadow) b86_jit_set_shadow(J, bb_shadow);
    bb_v15_original_interrupt = rt->hooks.interrupt;
    rt->hooks.interrupt = bb_v15_interrupt;
    bb_v35_original_in8=rt->hooks.in8;
    bb_v35_original_out8=rt->hooks.out8;
    rt->hooks.in8=bb_v35_pit_in8;
    rt->hooks.out8=bb_v35_pit_out8;
    printf("[bb-v35-pit] shared 8253/8254 I/O installed for native and interpreter\n");
    printf("[bb-v22] Shared INT10 + INT16 adapter installed original=%s\n",
           bb_v15_original_interrupt == md_msdos2_boot_interrupt ? "msdos2" : "other");
    fflush(stdout);
    b86_jit_set_max_block(J, 48);
    b86_jit_set_count_retired(J, 1);
    /* Tiering: translate an entry only after BB_HOT_THRESHOLD dispatches in
       the current cache generation; until then blitz86 interprets it. Keeps
       a program's hot loops resident in the SRAM code buffer instead of
       flushing it every frame (3DBENCH: 20-100 flushes per 10M insns -> 0-1). */
#ifndef BB_HOT_THRESHOLD
#define BB_HOT_THRESHOLD 128u
#endif
    b86_jit_set_hot_threshold(J, BB_HOT_THRESHOLD);
#if MICRODOS_TRANSLATION_SUPPORT
    memcpy(gen_seen, rt->code_page_generation, sizeof gen_seen);
#endif
#if BB_HAVE_TIMER
    add_repeating_timer_us(-(int64_t)BB_SLICE_US, slice_cb, NULL, &slice_timer);
#endif
    return 1;
}

void bb_live_set_enabled(int on) { enabled = on; }


/* ------------------------------------------------------------------------ */
/* v42: hang / fault diagnostics (RP2350). While mode 13h is active a 3 s    */
/* watchdog runs, fed every native slice; each slice also records the guest */
/* CS:IP in watchdog scratch[3]. A HardFault records PC/LR/CFSR/BFAR. Both  */
/* reboot; the next boot prints what was recorded. scratch[4..7] belong to  */
/* the SDK's watchdog_reboot, so only scratch[0..3] are used.               */
/* ------------------------------------------------------------------------ */
#define BB_DIAG_ARMED 0xB86A0001u
#define BB_DIAG_FAULT 0xB86F0002u
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
static int bb_wd_on;
/* v51: the fault record lives in WATCHDOG SCRATCH0-3 only. Those survive the
 * handler's watchdog reboot and a BOOTSEL session (the RAM record of v45/v50
 * did not: the BOOTSEL bootrom reuses SRAM, which is why v50 printed only
 * the legacy line). SCRATCH4-7 belong to the bootrom's reboot().
 *   scratch[0] = 0xB86F0000 | v51 | core<<15 | phase<<12 | DEBUGEVT<<11 |
 *                FORCED<<10 | VECTTBL<<9 | frame-in-stack<<8 | EXC_RETURN[6:0]
 *   scratch[1] = stacked PC   (0xFFFFFFFF when the frame address is not
 *                inside that core's stack: the "frame" would be garbage)
 *   scratch[2] = frame address (MSP/PSP at entry)
 *   scratch[3] = CFSR
 * The six v42-v50 reports all had 8-byte-aligned PCs and LR=0x10000000:
 * that looks like stale stack data, not real exception frames.             */
#define BB_FAULT_V51 0x00010000u               /* never set by v42-v50 records */
#define BB_PHASE_BOOT   1u
#define BB_PHASE_DOS    2u
#define BB_PHASE_VGA    3u
#define BB_PHASE_REBOOT 4u                     /* picotool reboot -f: BOOTSEL requested */
static volatile uint32_t bb_phase = BB_PHASE_BOOT;
#define BB_STACK_PAINT 0xCDCDCDCDu
static uint32_t bb_v51_paint_lo;              /* lowest painted core-0 stack word address */
void bb_fault_c(uint32_t *sf, uint32_t exc_lr)
{
    uint32_t core = *(volatile uint32_t *)0xD0000000u & 1u;            /* SIO CPUID */
    uint32_t lo = core ? (uint32_t)__StackOneBottom : (uint32_t)__StackBottom;
    uint32_t hi = core ? (uint32_t)__StackOneTop : (uint32_t)__StackTop;
    uint32_t fa = (uint32_t)sf;
    int in_stack = fa >= lo && fa + 32u <= hi && !(fa & 3u);
    uint32_t hfsr = *(volatile uint32_t *)0xE000ED2Cu;
    watchdog_hw->scratch[0] = 0xB86F0000u | BB_FAULT_V51 | (core << 15) | ((bb_phase & 7u) << 12) |
                              (((hfsr >> 31) & 1u) << 11) | (((hfsr >> 30) & 1u) << 10) |
                              (((hfsr >> 1) & 1u) << 9) | ((uint32_t)in_stack << 8) | (exc_lr & 0x7Fu);
    watchdog_hw->scratch[1] = in_stack ? sf[6] : 0xFFFFFFFFu;
    watchdog_hw->scratch[2] = fa;
    watchdog_hw->scratch[3] = *(volatile uint32_t *)0xE000ED28u;     /* CFSR */
    if (bb_phase == BB_PHASE_REBOOT) for (;;) {}  /* the bootrom's BOOTSEL reboot is already armed */
    watchdog_reboot(0, 0, 10);
    for (;;) {}
}
void __attribute__((naked)) isr_hardfault(void)
{
    __asm volatile(
        "tst lr, #4      \n"
        "ite eq          \n"
        "mrseq r0, msp   \n"
        "mrsne r0, psp   \n"
        "mov r1, lr      \n"
        "b bb_fault_c    \n");
}
/* picotool reboot -f -u: the USB reset interface calls reset_usb_boot() from
 * the USB IRQ while 3DBENCH runs on both cores. Quiesce first (linked with
 * -Wl,--wrap=reset_usb_boot by install_live.py). */
extern void __real_reset_usb_boot(uint32_t gpio_mask, uint32_t disable_mask);
void __wrap_reset_usb_boot(uint32_t gpio_mask, uint32_t disable_mask)
{
    bb_phase = BB_PHASE_REBOOT;
    if (bb_wd_on) { watchdog_disable(); bb_wd_on = 0; }
    if (get_core_num() == 0) multicore_reset_core1();   /* stop the LCD presenter */
    __real_reset_usb_boot(gpio_mask, disable_mask);
    for (;;) {}
}
/* v51: core-0 stack high-water mark (painted once at start, below the
 * current SP with a 256-byte margin) */
static void bb_v51_paint_stack(void)
{
    uint32_t sp; __asm volatile("mov %0, sp" : "=r"(sp));
    uint32_t lo = ((uint32_t)__StackBottom + 3u) & ~3u, top = (sp - 256u) & ~3u;
    for (uint32_t a = lo; a < top; a += 4u) *(volatile uint32_t *)a = BB_STACK_PAINT;
    bb_v51_paint_lo = lo;
}
static uint32_t bb_v51_stack_peak(void)
{
    if (!bb_v51_paint_lo) return 0;
    uint32_t a = bb_v51_paint_lo;
    while (a < (uint32_t)__StackTop && *(volatile uint32_t *)a == BB_STACK_PAINT) a += 4u;
    return (uint32_t)__StackTop - a;              /* bytes used at the deepest point */
}
static void bb_diag_boot_report(void)
{
    uint32_t m = watchdog_hw->scratch[0];
    static const char *const phases[8] = { "?", "boot", "dos", "vga", "reboot-request", "?", "?", "?" };
    if ((m & 0xFFFF0000u) == 0xB86F0000u && (m & BB_FAULT_V51)) {
        uint32_t core = (m >> 15) & 1u, ph = (m >> 12) & 7u, exc = m & 0x7Fu;
        uint32_t pc = watchdog_hw->scratch[1], fa = watchdog_hw->scratch[2], cfsr = watchdog_hw->scratch[3];
        uint32_t lo = core ? (uint32_t)__StackOneBottom : (uint32_t)__StackBottom;
        uint32_t hi = core ? (uint32_t)__StackOneTop : (uint32_t)__StackTop;
        printf("[bb-v51-fault] PREVIOUS RUN HARDFAULT core=%lu phase=%s hfsr:debugevt=%lu forced=%lu vecttbl=%lu cfsr=%08lX exc-return=..%02lX\n",
               (unsigned long)core, phases[ph], (unsigned long)((m >> 11) & 1u), (unsigned long)((m >> 10) & 1u),
               (unsigned long)((m >> 9) & 1u), (unsigned long)cfsr, (unsigned long)exc);
        printf("[bb-v51-fault] frame=%08lX stack=%08lX..%08lX (%s) stacked-pc=%08lX%s code=%p..%p\n",
               (unsigned long)fa, (unsigned long)lo, (unsigned long)hi,
               (m & 0x100u) ? "frame inside the stack" : "FRAME OUTSIDE THE STACK: overflow or corrupt SP",
               (unsigned long)pc, (m & 0x100u) ? "" : " (not read)", (void *)bb_code, (void *)(bb_code + sizeof bb_code));
        if (ph == BB_PHASE_REBOOT)
            printf("[bb-v51-fault] the fault happened while entering BOOTSEL for reflashing, not during the run\n");
    } else if ((m & 0xFFFF0000u) == 0xB86F0000u) {
        printf("[bb-v42-diag] PREVIOUS RUN HARDFAULT (pre-v51 record) pc=%08lX lr=%08lX cfsr=%08lX\n",
               (unsigned long)watchdog_hw->scratch[1], (unsigned long)watchdog_hw->scratch[2],
               (unsigned long)watchdog_hw->scratch[3]);
    }
    else if (m == BB_DIAG_ARMED && watchdog_enable_caused_reboot())
        printf("[bb-v42-diag] PREVIOUS RUN HUNG (3 s watchdog) last native slice at guest %04lX:%04lX, slice %lu\n",
               (unsigned long)(watchdog_hw->scratch[3] >> 16), (unsigned long)(watchdog_hw->scratch[3] & 0xFFFFu),
               (unsigned long)watchdog_hw->scratch[1]);
    watchdog_hw->scratch[0] = 0;
    fflush(stdout);
    bb_v51_paint_stack();
    bb_phase = BB_PHASE_DOS;
}
static void bb_diag_pause(int pause)
{
    if (!bb_wd_on) return;
    if (pause) watchdog_disable();
    else { watchdog_enable(3000, 1); watchdog_update(); }
}
static void bb_diag_slice(void)
{
    int vga = bb_vga_active();
    if (bb_phase != BB_PHASE_REBOOT) bb_phase = vga ? BB_PHASE_VGA : BB_PHASE_DOS;
    if (vga && !bb_wd_on) {
        watchdog_hw->scratch[0] = BB_DIAG_ARMED;
        watchdog_hw->scratch[1] = 0;
        watchdog_enable(3000, 1);
        bb_wd_on = 1;
    } else if (!vga && bb_wd_on) {          /* back at the DOS prompt: may block on input */
        watchdog_disable();
        watchdog_hw->scratch[0] = 0;
        bb_wd_on = 0;
    }
    if (bb_wd_on) {
        watchdog_hw->scratch[3] = (C.seg[B86_CS] << 16) | (C.ip & 0xFFFFu);
        watchdog_hw->scratch[1]++;
        watchdog_update();
    }
}
#else
static void bb_diag_pause(int pause) { (void)pause; }
static void bb_diag_boot_report(void) {}
static void bb_diag_slice(void) {}
#endif
static void bb_time_freeze(uint64_t us)
{
    if (!us) return;
    bb_v24_start_us += us;                       /* BIOS tick at 0040:006C */
    for (unsigned i = 0; i < 3u; ++i) bb_pit.c[i].epoch_us += us;   /* PIT counters */
    bb_irq36.anchor_us = bb_pit.c[0].epoch_us;   /* keep IRQ0's period count */
}
B86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)
{
    (void)left;
    if (!enabled || failed || rt->stop_reason != MD_STOP_NONE) return 0;
    if (R == NULL && !start(rt)) return 0;
    /* v23: JIT restored after mode 13h; the v19 control gate is removed. */
    bb_v23_poll_input();
    bb_diag_slice();                      /* v42: watchdog + last guest CS:IP */
    bb_v25_bios_time();
    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());
    if (rt == R && rt->cpu.cs == bios_seg) bb_v40_release("BIOS segment");
    if (rt != R || rt->cpu.cs == bios_seg) {
        if (bb_video_seen && rt == R && bb_log_n(++bb_interp_skips)) {
            printf("[bb-handoff] interpreter-owned n=%lu cs:ip=%04X:%04X bios=%04X\n",
                (unsigned long)bb_interp_skips,(unsigned)rt->cpu.cs,(unsigned)rt->cpu.ip,(unsigned)bios_seg);
            fflush(stdout);
        }
        return 0;
    }

    if (bb_v40_vga_pending) { bb_v40_vga_pending = 0; bb_v40_vga_sync(); }
    bb_v40_tick();
    uint64_t t0 = bb_now_us();
    track_pages();
    sync_pages();                       /* writes made while microDOS ran */
    uint64_t t1 = bb_now_us();
    st.sync_us += t1 - t0;
    to_b86();
    C.trap_cs = bios_seg;
    C.irq = 0;
    C.icnt = 0;
#ifdef BB_DEBUG
    fprintf(stderr, "[bb] slice %llu enter %04X:%04X\n", (unsigned long long)st.slices, rt->cpu.cs, rt->cpu.ip);
#endif
    uint64_t m1 = bb_xip_misses();
    ++bb_trace_runs;
    if(0) {
        printf("[bb-trace] JIT enter n=%lu cs:ip=%04X:%04X ax=%04X sp=%04X\n",
               (unsigned long)bb_trace_runs,(unsigned)C.seg[B86_CS],(unsigned)C.ip,
               (unsigned)C.r[B86_AX],(unsigned)C.r[B86_SP]);
        fflush(stdout);
    }
    if (bb_video_seen) ++bb_post_video_slices;
    if(0) {
        ++bb_handoff_n;
        bb_cpu_snapshot("jit-enter",&C,-1,0);
    }
    if(bb_video_seen)bb_v7_record(2,(uint16_t)C.seg[B86_CS],(uint16_t)C.ip,
        (uint16_t)C.seg[B86_SS],(uint16_t)C.r[B86_SP],(uint16_t)C.r[B86_AX],
        (uint16_t)C.seg[B86_DS],(uint16_t)C.seg[B86_ES],b86_get_flags(&C),0);
    /* Diagnostic only: reduce the dispatch budget after the third INT10
       palette setup to improve boundary granularity near the bad transfer.
       Dispatches are NOT individual x86 instructions. */
    /* v13: fixed budget from the FIRST mode-13 return, independent of
       palette count, suspicious-state detection or previously observed path. */
    const unsigned bb_v10_budget = BB_SLICE_DISPATCH;   /* v33: the v13 256-dispatch diagnostic budget is gone */
    if (bb_v10_budget != BB_SLICE_DISPATCH) ++bb_v10_small_dispatches;

    const uint16_t v13_before_cs=(uint16_t)C.seg[B86_CS];
    const uint16_t v13_before_ip=(uint16_t)C.ip;
    const uint16_t v13_before_sp=(uint16_t)C.r[B86_SP];
    const uint16_t v17_before_ss=(uint16_t)C.seg[B86_SS];
    uint64_t v24_jit_t0=bb_now_us();
    int rc = b86_jit_run(&C, bb_v10_budget);
    bb_v24_jit_us+=bb_now_us()-v24_jit_t0;
    ++bb_v24_jit_calls;
    bb_v24_jit_insns+=C.icnt;
    bb_v25_bios_time();
    if(C.icnt==0u){++bb_v24_zero;if(rc==B86_TRAP)++bb_v24_zero_trap;}
    if(bb_video_seen && bb_v24_jit_calls>0 && (bb_v24_jit_calls%8192u)==0u){
        bb_v24_last_bda_tick=bb_v24_bda_tick();
        bb_v24_report();
    }

    if (0) {
        printf("[bb-v13] HANDOFF slice=%lu from=%04X:%04X sp=%04X to=%04X:%04X sp=%04X rc=%d retired=%lu interpreter-next=%u\n",
               (unsigned long)bb_post_video_slices,
               (unsigned)v13_before_cs,(unsigned)v13_before_ip,(unsigned)v13_before_sp,
               (unsigned)C.seg[B86_CS],(unsigned)C.ip,(unsigned)C.r[B86_SP],rc,
               (unsigned long)C.icnt,(unsigned)(C.icnt==0u && rc!=B86_HALT));
        fflush(stdout);
    }
    if(bb_video_seen)bb_v7_record(3,(uint16_t)C.seg[B86_CS],(uint16_t)C.ip,
        (uint16_t)C.seg[B86_SS],(uint16_t)C.r[B86_SP],(uint16_t)C.r[B86_AX],
        (uint16_t)C.seg[B86_DS],(uint16_t)C.seg[B86_ES],b86_get_flags(&C),C.icnt);
    if(0) {
        ++bb_handoff_n;
        bb_cpu_snapshot("jit-leave",&C,rc,C.icnt);
    }
    if(0) {
        printf("[bb-trace] JIT leave n=%lu rc=%d retired=%lu cs:ip=%04X:%04X\n",
               (unsigned long)bb_trace_runs,rc,(unsigned long)C.icnt,
               (unsigned)C.seg[B86_CS],(unsigned)C.ip);
        fflush(stdout);
    }
    st.native_us += bb_now_us() - t1;
    st.native_misses += bb_xip_misses() - m1;
    last_rc = rc;
    to_md();
    /* Record the FIRST post-mode-13 visit to the IVT as data, not a fault.
       Memory 0000:0000-0000:03FF stores vectors, so this is a useful
       control-flow waypoint regardless of the actual originating opcode. */
    if (bb_video_seen && !bb_v10_ivt_seen &&
        bb_v6_linear(rt->cpu.cs,rt->cpu.ip) < 0x400u) {
        bb_v10_ivt_seen = 1;
        printf("[bb-v10] FIRST-IVT cs:ip=%04X:%04X rc=%d retired=%lu small-dispatches=%lu\n",
               rt->cpu.cs,rt->cpu.ip,rc,(unsigned long)C.icnt,
               (unsigned long)bb_v10_small_dispatches);
        bb_v7_dump("first-ivt");
    }
    if (bb_v17_guard(rt,"jit-exit",v13_before_cs,v13_before_ip,
                     v17_before_ss,v13_before_sp,C.icnt,rc)) {
        rt->instructions += C.icnt; st.retired += C.icnt; ++st.slices;
        return 1;
    }
    (void)bb_v7_check(rt,"jit-exit");
#ifdef BB_DEBUG
    fprintf(stderr, "[bb]   rc=%d exit %04X:%04X retired=%u\n", rc, rt->cpu.cs, rt->cpu.ip, C.icnt);
#endif
#if defined(BLITZBUS_LCD_CONSOLE) && BLITZBUS_LCD_CONSOLE
    /* Cooperative VGA presentation: one 12-row tile per eligible dispatch.
       Each call returns quickly so DOS execution and USB keyboard service continue.
       The LCD presenter maintains its own 1 ms strip cadence. */
    if (bb_video_seen) {
        uint64_t t=bb_now_us();
        bb_lcd_vga_tick();
        bb_v24_lcd_us+=bb_now_us()-t;
        ++bb_v24_lcd_calls;
    }
#endif
    rt->instructions += C.icnt;
    st.retired += C.icnt;
    ++st.slices;
    if (rc == B86_TRAP) ++st.traps;
    if (rc == B86_HALT) { ++st.halts; rt->stop_reason = MD_STOP_HALT; }
    C.irq = 0;
    return C.icnt != 0 || rc == B86_HALT || rt->stop_reason != MD_STOP_NONE;
}

void bb_live_get_stats(BbLiveStats *s)
{
    *s = st;
    if (J) {
        const B86JitStats *js = b86_jit_stats(J);
        s->translate_us = js->translate_us;
        s->flushes = js->flushes;
        s->fast_dispatches = js->fast_dispatches;
        s->dispatches = js->dispatches;
        s->translate_misses = js->translate_misses;
        s->rt_step = js->rt_step; s->rt_cond = js->rt_cond; s->rt_flags = js->rt_flags;
        s->rt_light = js->rt_light; s->rt_smc = js->rt_smc; s->rt_rep = js->rt_rep;
        s->blocks = js->blocks;
    }
    s->tr_pages = trpool_used;
}

/* ---- compatibility accessors ---------------------------------------------- */
uint64_t bb_live_retired(void) { return st.retired; }
uint64_t bb_live_blocks(void) { return J ? b86_jit_stats(J)->blocks : 0; }
int bb_live_ready(void) { return J != NULL && !failed && enabled; }
void bb_live_diag(uint64_t *attempts, uint64_t *candidates, uint64_t *inits, uint64_t *initfails,
                  uint64_t *runfails, uint16_t *cs, uint16_t *ip, uint8_t *op)
{
    *attempts = st.slices; *candidates = st.traps; *inits = J != NULL; *initfails = failed;
    *runfails = 0; *cs = R ? R->cpu.cs : 0; *ip = R ? R->cpu.ip : 0; *op = 0;
}
const char *bb_live_diff_field(void) { return failed ? fail_reason : "owner-mode"; }
const char *bb_live_fail_reason(void) { return fail_reason; }
uint16_t bb_live_diff_expected(void) { return 0; }
uint16_t bb_live_diff_actual(void) { return 0; }
void bb_live_status(int *rc, uint64_t *delta, uint16_t *expected_ip, uint16_t *actual_ip,
                    uint64_t *verified, uint64_t *fallback, uint64_t *disabled,
                    uint64_t *budget, uint64_t *exit_count, uint64_t *halt, uint64_t *other)
{
    const B86JitStats *js = J ? b86_jit_stats(J) : NULL;
    *rc = last_rc; *delta = st.retired; *expected_ip = 0; *actual_ip = 0;
    *verified = st.hook_calls; *fallback = st.page_invalidations; *disabled = !enabled;
    *budget = js ? js->chains : 0; *exit_count = js ? js->smc_invalidations : 0;
    *halt = st.halts; *other = js ? js->helper_insns : 0;
}

struct B86Jit *bb_live_jit(void) { return J; }

/* Telemetry for the Ctrl+] block: cumulative timing plus a delta line since
   the previous call (per-phase profiles). */
void bb_live_print_extra(void (*say)(const char *fmt, ...))
{
    static BbLiveStats prev;
    BbLiveStats s;
    bb_live_get_stats(&s);
    bb_v24_last_bda_tick=bb_v24_bda_tick();
    say("[bb-v24] PROFILE wall-ms=%llu jit-calls=%llu jit-zero=%llu jit-insns=%llu jit-ms=%llu interp-calls=%llu interp-insns=%llu lcd-calls=%llu lcd-ms=%llu hash-ms=%llu bda-ticks=%lu->%lu\n",
        (unsigned long long)(bb_video_seen?(bb_now_us()-bb_v24_start_us)/1000u:0),
        (unsigned long long)bb_v24_jit_calls,(unsigned long long)bb_v24_zero,
        (unsigned long long)bb_v24_jit_insns,(unsigned long long)(bb_v24_jit_us/1000u),
        (unsigned long long)bb_v24_interp_calls,(unsigned long long)bb_v24_interp_insns,
        (unsigned long long)bb_v24_lcd_calls,(unsigned long long)(bb_v24_lcd_us/1000u),
        (unsigned long long)(bb_v24_hash_us/1000u),
        (unsigned long)bb_v24_start_bda_tick,(unsigned long)bb_v24_last_bda_tick);
    say("[bb-v23] STAT ticks=%lu changed-samples=%lu keys=%lu dropped=%lu input-polls=%lu int16=%u\n",
        (unsigned long)bb_v23_lcd_ticks,(unsigned long)bb_v23_changed_samples,
        (unsigned long)bb_v23_keys,(unsigned long)bb_v23_key_drop,
        (unsigned long)bb_v23_polls,bb_v22_key_calls);
    say("[bb-live-time] native=%llu ms (translate=%llu ms) sync=%llu ms flushes=%llu dispatches=%llu fast=%llu native-misses=%llu translate-misses=%llu\n",
        (unsigned long long)(s.native_us / 1000u), (unsigned long long)(s.translate_us / 1000u),
        (unsigned long long)(s.sync_us / 1000u), (unsigned long long)s.flushes,
        (unsigned long long)s.dispatches, (unsigned long long)s.fast_dispatches,
        (unsigned long long)s.native_misses, (unsigned long long)s.translate_misses);
    say("[bb-live-delta] retired=%llu native=%llu ms translate=%llu ms blocks=%llu native-misses=%llu translate-misses=%llu "
        "rt-step=%llu rt-cond=%llu rt-flags=%llu rt-light=%llu rt-smc=%llu traps=%llu\n",
        (unsigned long long)(s.retired - prev.retired), (unsigned long long)((s.native_us - prev.native_us) / 1000u),
        (unsigned long long)((s.translate_us - prev.translate_us) / 1000u), (unsigned long long)(s.blocks - prev.blocks),
        (unsigned long long)(s.native_misses - prev.native_misses), (unsigned long long)(s.translate_misses - prev.translate_misses),
        (unsigned long long)(s.rt_step - prev.rt_step), (unsigned long long)(s.rt_cond - prev.rt_cond),
        (unsigned long long)(s.rt_flags - prev.rt_flags), (unsigned long long)(s.rt_light - prev.rt_light),
        (unsigned long long)(s.rt_smc - prev.rt_smc), (unsigned long long)(s.traps - prev.traps));
    prev = s;
}
