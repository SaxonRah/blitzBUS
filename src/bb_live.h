#ifndef BB_LIVE_H
#define BB_LIVE_H
/* blitzBUS live backend: blitz86 OWNS guest execution inside the microDOS
 * DOS system loop. microDOS keeps the BIOS segment (driver trampolines),
 * its INT hooks (console/disk/clock HLE) and port I/O; blitz86 runs
 * everything else natively and commits state back after every slice. */
#include "microdos/runtime.h"
#include <stdint.h>

/* Run guest code natively from the current CS:IP. Returns nonzero if any
   architectural progress was made (the caller loops), 0 to let microDOS
   execute (BIOS segment, backend disabled or failed to start). */
int bb_live_try(MdRuntime *rt, uint64_t left);

/* Runtime switch (default on). Off = microDOS interprets everything. */
void bb_live_set_enabled(int on);

typedef struct BbLiveStats {
    uint64_t retired;          /* guest instructions retired by blitz86   */
    uint64_t slices;           /* bb_live_try calls that ran native code  */
    uint64_t traps;            /* slices ended by reaching the BIOS seg   */
    uint64_t hook_calls;       /* INT vectors serviced by microDOS hooks  */
    uint64_t page_syncs;         /* pages microDOS wrote (checked)        */
    uint64_t page_invalidations; /* code lines that actually changed       */
    uint64_t halts;
    uint64_t native_us;          /* time inside b86_jit_run (incl. translate) */
    uint64_t translate_us;       /* of which translating (needs B86_NOW)     */
    uint64_t sync_us;            /* checking microDOS writes                 */
    uint64_t flushes, dispatches, fast_dispatches;
    uint64_t tr_pages;           /* pages with byte-exact write filtering    */
    uint64_t native_misses;      /* XIP/QMI misses inside b86_jit_run (RP2350) */
    uint64_t translate_misses;   /* of which while translating               */
    uint64_t rt_step, rt_cond, rt_flags, rt_light, rt_smc, rt_rep, blocks;
} BbLiveStats;
uint64_t bb_xip_misses(void);
void bb_live_print_extra(void (*say)(const char *fmt, ...));
uint64_t bb_now_us(void);
void bb_live_get_stats(BbLiveStats *s);
const char *bb_live_fail_reason(void);

/* Compatibility accessors used by the generated Pico stats block. */
uint64_t bb_live_retired(void);
uint64_t bb_live_blocks(void);
int bb_live_ready(void);
void bb_live_diag(uint64_t *attempts, uint64_t *candidates, uint64_t *inits, uint64_t *initfails,
                  uint64_t *runfails, uint16_t *cs, uint16_t *ip, uint8_t *op);
const char *bb_live_diff_field(void);
uint16_t bb_live_diff_expected(void);
uint16_t bb_live_diff_actual(void);
void bb_live_status(int *rc, uint64_t *delta, uint16_t *expected_ip, uint16_t *actual_ip,
                    uint64_t *verified, uint64_t *fallback, uint64_t *disabled,
                    uint64_t *budget, uint64_t *exit_count, uint64_t *halt, uint64_t *other);
#endif
