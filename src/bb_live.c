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
#include "b86.h"
#include "msdos2_boot.h"
#include <string.h>
#ifdef BB_DEBUG
#include <stdio.h>
#endif
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#include "pico/time.h"
#define BB_HAVE_TIMER 1
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
#define BB_META_BYTES (384u * 1024u)
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
static struct B86Jit *J;
static MdRuntime *R;
static uint16_t bios_seg;
static int enabled = 1, failed = 0;
static uint32_t gen_seen[MD_X86_CODE_PAGE_COUNT];
static BbLiveStats st;
static int last_rc = -1;
#if BB_HAVE_TIMER
static struct repeating_timer slice_timer;
static bool slice_cb(struct repeating_timer *t) { (void)t; C.irq |= 1u; return true; }
#endif

static void to_b86(void)
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

static void to_md(void)
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

/* Every page tracked: microDOS bumps code_page_generation on any write it
   performs (hooks, BIOS-segment interpretation). Translation-side stores
   go straight to memory and are covered by blitz86's own SMC checks. */
static void track_all_pages(void)
{
#if MICRODOS_TRANSLATION_SUPPORT
    for (unsigned p = 0; p < MD_X86_CODE_PAGE_COUNT; ++p)
        R->code_page_executable[p] |= MD_X86_PAGE_TRANSLATED;
#endif
}

static void sync_pages(void)
{
#if MICRODOS_TRANSLATION_SUPPORT
    for (unsigned p = 0; p < MD_X86_CODE_PAGE_COUNT; ++p) {
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

static int hook_int(B86Cpu *c, uint8_t v)
{
#ifdef BB_DEBUG
    fprintf(stderr, "[bb]   int %02X at %04X:%04X\n", v, (unsigned)c->seg[B86_CS], (unsigned)c->ip);
#endif
    if (R->hooks.interrupt == NULL) return 0;
    to_md();                                    /* c->ip = return address */
    if (!R->hooks.interrupt(R, v, R->hooks.user)) return 0;
    ++st.hook_calls;
    to_b86();
    sync_pages();
    if (R->stop_reason != MD_STOP_NONE) c->irq |= 1u;
    return 1;
}
static uint8_t hook_in(B86Cpu *c, uint16_t port)
{
    (void)c;
    return R->hooks.in8 ? R->hooks.in8(R, port, R->hooks.user) : 0xFFu;
}
static void hook_out(B86Cpu *c, uint16_t port, uint8_t v)
{
    (void)c;
    if (R->hooks.out8) R->hooks.out8(R, port, v, R->hooks.user);
}

static int start(MdRuntime *rt)
{
    R = rt;
    if (rt->hooks.interrupt != md_msdos2_boot_interrupt || rt->hooks.user == NULL) { failed = 1; fail_reason = "not-msdos2-boot"; return 0; }
    if (((uintptr_t)rt->cpu.memory & 63u) != 0) { failed = 1; fail_reason = "guest-not-64-aligned"; return 0; }
    bios_seg = ((const MdMsdos2Boot *)rt->hooks.user)->bios_segment;
    b86_init(&C, rt->cpu.memory);      /* guest buffer >= B86_MEM_BYTES (A20-on model) */
    C.int_hook = hook_int;
    C.in8 = hook_in;
    C.out8 = hook_out;
#if defined(__linux__)
    bb_code = mmap(NULL, BB_CODE_BYTES, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (bb_code == MAP_FAILED) { failed = 1; fail_reason = "mmap"; return 0; }
#endif
    J = b86_jit_create_ex(&C, bb_code, BB_CODE_BYTES, bb_hot, sizeof bb_hot);
    if (J == NULL) { failed = 1; fail_reason = "jit-create"; return 0; }
#if !(defined(PICO_ON_DEVICE) && PICO_ON_DEVICE)
    bb_shadow = aligned_alloc(64, (B86_MEM_BYTES + 63u) & ~63u);
#endif
    if (bb_shadow) b86_jit_set_shadow(J, bb_shadow);
    b86_jit_set_max_block(J, 48);
    b86_jit_set_count_retired(J, 1);
#if MICRODOS_TRANSLATION_SUPPORT
    memcpy(gen_seen, rt->code_page_generation, sizeof gen_seen);
#endif
#if BB_HAVE_TIMER
    add_repeating_timer_us(-(int64_t)BB_SLICE_US, slice_cb, NULL, &slice_timer);
#endif
    return 1;
}

void bb_live_set_enabled(int on) { enabled = on; }

int bb_live_try(MdRuntime *rt, uint64_t left)
{
    (void)left;
    if (!enabled || failed || rt->stop_reason != MD_STOP_NONE) return 0;
    if (R == NULL && !start(rt)) return 0;
    if (rt != R || rt->cpu.cs == bios_seg) return 0;

    track_all_pages();
    sync_pages();                       /* writes made while microDOS ran */
    to_b86();
    C.trap_cs = bios_seg;
    C.irq = 0;
    C.icnt = 0;
#ifdef BB_DEBUG
    fprintf(stderr, "[bb] slice %llu enter %04X:%04X\n", (unsigned long long)st.slices, rt->cpu.cs, rt->cpu.ip);
#endif
    int rc = b86_jit_run(&C, BB_SLICE_DISPATCH);
    last_rc = rc;
    to_md();
#ifdef BB_DEBUG
    fprintf(stderr, "[bb]   rc=%d exit %04X:%04X retired=%u\n", rc, rt->cpu.cs, rt->cpu.ip, C.icnt);
#endif
    rt->instructions += C.icnt;
    st.retired += C.icnt;
    ++st.slices;
    if (rc == B86_TRAP) ++st.traps;
    if (rc == B86_HALT) { ++st.halts; rt->stop_reason = MD_STOP_HALT; }
    C.irq = 0;
    return C.icnt != 0 || rc == B86_HALT || rt->stop_reason != MD_STOP_NONE;
}

void bb_live_get_stats(BbLiveStats *s) { *s = st; }

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
