/* blitzBUS v0.7.6.2: reference-first, read-only differential JIT validation.
 * microDOS always owns authoritative state. No JIT state is committed.
 * Only one-byte, register/flags-only opcodes are eligible.
 */
#include "bb_live.h"
#include "b86.h"
#include <string.h>
#define BB_CODE_BYTES (32u * 1024u)
static uint8_t bb_code[BB_CODE_BYTES] __attribute__((aligned(16)));
static B86Cpu bb_cpu;
static struct B86Jit *bb_jit;
static MdRuntime *bb_rt;
static uint64_t bb_count, bb_blocks;
static uint64_t bb_attempts, bb_candidates, bb_init_attempts, bb_init_failures, bb_runtime_failures;
static uint16_t bb_last_cs, bb_last_ip, bb_diff_expected, bb_diff_actual;
static uint8_t bb_last_op;
static const char *bb_diff_field="none";
static int bb_failed;
static int bb_last_rc=-1;
static uint64_t bb_last_delta, bb_verified, bb_fallback, bb_disabled;
static uint16_t bb_expected_ip, bb_actual_ip;
static uint64_t bb_budget_stops, bb_exit_stops, bb_halt_stops, bb_other_stops;

/* NOP and flag-control are a narrow, memory-side-effect-free starting gate.
 * INC/DEC require extra per-flag semantics and are intentionally excluded. */
static int safe_opcode(uint8_t op) {
    return op == 0x90u || op == 0xF5u || op == 0xF8u || op == 0xF9u ||
           op == 0xFCu || op == 0xFDu;
}

static int mismatch(const char *field, uint16_t expected, uint16_t actual) {
    if (expected == actual) return 0;
    bb_diff_field=field;
    bb_diff_expected=expected;
    bb_diff_actual=actual;
    ++bb_runtime_failures;
    bb_failed=1;
    return 1;
}

int bb_live_try(MdRuntime *rt) {
    unsigned i;
    uint32_t phys;
    uint8_t op;
    uint16_t before_ip, before_cs, expected_flags, actual_flags;
    uint64_t n_before, blocks_before;
    const B86JitStats *st;
    int rc;
    if (!rt || rt->stop_reason != MD_STOP_NONE) return 0;
    if (bb_failed) { ++bb_disabled; return 0; }
    ++bb_attempts;
    phys=((uint32_t)rt->cpu.cs << 4) + rt->cpu.ip;
    if (phys >= MD_X86_ADDRESS_SPACE || phys + 64u >= MD_X86_ADDRESS_SPACE) return 0;
    op=rt->cpu.memory[phys];
    if (!safe_opcode(op)) { ++bb_fallback; return 0; }
    ++bb_candidates;
    bb_last_cs=rt->cpu.cs; bb_last_ip=rt->cpu.ip; bb_last_op=op;
    if (!bb_jit) {
        ++bb_init_attempts;
        b86_init(&bb_cpu,rt->cpu.memory);
        bb_cpu.amask=0xFFFFFu;
        bb_cpu.exact_wrap=1u;
        bb_jit=b86_jit_create(&bb_cpu,bb_code,sizeof(bb_code));
        if (!bb_jit) { ++bb_init_failures; bb_failed=1; bb_diff_field="init"; return 0; }
        b86_jit_set_single_step(bb_jit,1);
        b86_jit_set_no_chain(bb_jit,1);
        bb_rt=rt;
    }
    if (bb_rt != rt) return 0;
    for(i=0;i<8;i++) bb_cpu.r[i]=rt->cpu.r[i];
    b86_set_seg(&bb_cpu,B86_ES,rt->cpu.es);
    b86_set_seg(&bb_cpu,B86_CS,rt->cpu.cs);
    b86_set_seg(&bb_cpu,B86_SS,rt->cpu.ss);
    b86_set_seg(&bb_cpu,B86_DS,rt->cpu.ds);
    bb_cpu.ip=rt->cpu.ip;
    b86_set_flags(&bb_cpu,md_x86_flags(&rt->cpu));
    bb_cpu.irq=0;
    before_ip=rt->cpu.ip; before_cs=rt->cpu.cs;
    st=b86_jit_stats(bb_jit);
    n_before=st->guest_insns; blocks_before=st->blocks;

    /* Reference is authoritative: a failing native step cannot damage
     * the guest register state. Eligible instructions do not write memory. */
    (void)md_interp_step(rt);
    if (rt->stop_reason != MD_STOP_NONE) { bb_failed=1; bb_diff_field="reference-stop"; return 1; }
    expected_flags=md_x86_flags(&rt->cpu);
    rc=b86_jit_run(&bb_cpu,1u);
    st=b86_jit_stats(bb_jit);
    bb_last_rc=rc;
    bb_last_delta=st->guest_insns-n_before;
    bb_expected_ip=rt->cpu.ip;
    bb_actual_ip=(uint16_t)bb_cpu.ip;
    if (rc==B86_BUDGET) ++bb_budget_stops;
    else if (rc==B86_EXIT) ++bb_exit_stops;
    else if (rc==B86_HALT) ++bb_halt_stops;
    else ++bb_other_stops;
    if (rc != B86_BUDGET) {
        /* Reference already committed. Never copy the native state. */
        bb_diff_field=(rc==B86_EXIT)?"jit-exit":
                      (rc==B86_HALT)?"jit-halt":
                      (rc==B86_BUDGET)?"jit-budget":"jit-unknown-rc";
        bb_diff_expected=(uint16_t)B86_BUDGET;
        bb_diff_actual=(uint16_t)rc;
        ++bb_runtime_failures;
        bb_failed=1;
        return 1;
    }
    /* A B86_BUDGET return with the expected IP and CPU state is valid.
     * B86JitStats.guest_insns may not increment on every dispatch, so its
     * delta is telemetry rather than a correctness gate. */
    if (mismatch("CS",rt->cpu.cs,(uint16_t)bb_cpu.seg[B86_CS]) ||
        mismatch("IP",rt->cpu.ip,(uint16_t)bb_cpu.ip) ||
        mismatch("ES",rt->cpu.es,(uint16_t)bb_cpu.seg[B86_ES]) ||
        mismatch("SS",rt->cpu.ss,(uint16_t)bb_cpu.seg[B86_SS]) ||
        mismatch("DS",rt->cpu.ds,(uint16_t)bb_cpu.seg[B86_DS])) return 1;
    for (i=0;i<8;i++) {
        if (mismatch((const char*[]){"AX","CX","DX","BX","SP","BP","SI","DI"}[i],
                     rt->cpu.r[i],(uint16_t)bb_cpu.r[i])) return 1;
    }
    actual_flags=b86_get_flags(&bb_cpu);
    /* Exclude reserved/undefined bits; compare architectural status/control. */
    if (mismatch("FLAGS",expected_flags & 0x0FD5u,actual_flags & 0x0FD5u)) return 1;
    if (mismatch("reference-CS",before_cs,rt->cpu.cs)) return 1;
    if (mismatch("reference-IP",(uint16_t)(before_ip+1u),rt->cpu.ip)) return 1;
    ++bb_verified;
    ++bb_count;
    bb_blocks += st->blocks-blocks_before;
    return 1;
}
uint64_t bb_live_retired(void) { return bb_count; }
uint64_t bb_live_blocks(void) { return bb_blocks; }
int bb_live_ready(void) { return bb_jit != 0 && !bb_failed; }
void bb_live_diag(uint64_t *attempts, uint64_t *candidates, uint64_t *inits, uint64_t *initfails,
                  uint64_t *runfails, uint16_t *cs, uint16_t *ip, uint8_t *op) {
    *attempts=bb_attempts; *candidates=bb_candidates; *inits=bb_init_attempts;
    *initfails=bb_init_failures; *runfails=bb_runtime_failures;
    *cs=bb_last_cs; *ip=bb_last_ip; *op=bb_last_op;
}
const char *bb_live_diff_field(void) { return bb_diff_field; }
uint16_t bb_live_diff_expected(void) { return bb_diff_expected; }
uint16_t bb_live_diff_actual(void) { return bb_diff_actual; }

void bb_live_status(int *rc, uint64_t *delta, uint16_t *expected_ip, uint16_t *actual_ip,
                    uint64_t *verified, uint64_t *fallback, uint64_t *disabled,
                    uint64_t *budget, uint64_t *exit_count, uint64_t *halt, uint64_t *other) {
    *rc=bb_last_rc; *delta=bb_last_delta;
    *expected_ip=bb_expected_ip; *actual_ip=bb_actual_ip;
    *verified=bb_verified; *fallback=bb_fallback; *disabled=bb_disabled;
    *budget=bb_budget_stops; *exit_count=bb_exit_stops;
    *halt=bb_halt_stops; *other=bb_other_stops;
}
