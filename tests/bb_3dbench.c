/* blitzBUS host 3DBENCH profile: boot MS-DOS 2.0 through microDOS's DOS
 * loop with the blitzBUS live backend (bb_live.c + bb_vga.c, as on the Pico),
 * type 3DBENCH and run BUDGET guest instructions, printing blitz86 counters
 * every 10M instructions on stderr and totals at the end.
 *
 *   BUDGET=250000000 qemu-arm build-3db/bb_3dbench MSDOS.SYS 3db.img
 *
 * Build with tests/build_3dbench.sh. -DB86_HELPER_HISTO adds an
 * interpreter-fallback histogram by opcode. */
#include "md_dos2_system.h"
#include "bb_live.h"
#include "b86.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define OUT_MAX (256u * 1024u)
#ifndef BUDGET
#define BUDGET 200000000ull
#endif

typedef struct Step { const char *after; const char *keys; } Step;
static const Step script[] = {
    { "Enter new date", "\r" },
    { "Enter new time", "\r" },
    { "A>", "3DBENCH\r" },
};
#define NSTEP (sizeof script / sizeof script[0])

typedef struct E2e {
    char out[OUT_MAX];
    size_t len, step, from;
    const char *keys;
    uint8_t *disk;
    size_t disk_size;
    int quiet;
} E2e;

static void release(E2e *e)
{
    while ((e->keys == NULL || *e->keys == '\0') && e->step < NSTEP) {
        e->out[e->len] = '\0';
        const char *hit = strstr(e->out + e->from, script[e->step].after);
        if (!hit) return;
        e->from = (size_t)(hit - e->out) + strlen(script[e->step].after);
        e->keys = script[e->step].keys;
        ++e->step;
    }
}
static void con_write(void *u, const uint8_t *d, size_t n)
{
    E2e *e = u;
    for (size_t i = 0; i < n && e->len + 1 < OUT_MAX; ++i) e->out[e->len++] = (char)d[i];
    if (!e->quiet) fwrite(d, 1, n, stdout);
}
static bool con_peek(void *u, uint8_t *v)
{
    E2e *e = u;
    release(e);
    if (e->keys == NULL || *e->keys == '\0') return false;
    *v = (uint8_t)*e->keys;
    return true;
}
static bool con_read(void *u, uint8_t *v)
{
    E2e *e = u;
    if (!con_peek(u, v)) return false;
    ++e->keys;
    return true;
}
static void con_flush(void *u) { (void)u; }
static bool disk_read(void *u, uint32_t sector, uint8_t *data, size_t size)
{
    E2e *e = u;
    if ((size_t)sector * size + size > e->disk_size) return false;
    memcpy(data, e->disk + (size_t)sector * size, size);
    return true;
}
static bool disk_write(void *u, uint32_t sector, const uint8_t *data, size_t size)
{
    E2e *e = u;
    if ((size_t)sector * size + size > e->disk_size) return false;
    memcpy(e->disk + (size_t)sector * size, data, size);
    return true;
}
static uint8_t *load(const char *path, size_t *size)
{
    FILE *fp = fopen(path, "rb");
    if (!fp) return NULL;
    fseek(fp, 0, SEEK_END);
    long n = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    uint8_t *d = malloc((size_t)n);
    if (!d || fread(d, 1, (size_t)n, fp) != (size_t)n) { fclose(fp); free(d); return NULL; }
    fclose(fp);
    *size = (size_t)n;
    return d;
}

int main(int argc, char **argv)
{
    static E2e e;
    static MdDos2System sys;
    size_t ksz = 0;
    int interp = 0;
    const char *expect = NULL;
    if (argc < 3) { fprintf(stderr, "usage: %s MSDOS.SYS disk.img [--interp] [--expect-checksum X] [--quiet]\n", argv[0]); return 2; }
    for (int i = 3; i < argc; ++i) {
        if (!strcmp(argv[i], "--interp")) interp = 1;
        else if (!strcmp(argv[i], "--quiet")) e.quiet = 1;
        else if (!strcmp(argv[i], "--expect-checksum") && i + 1 < argc) expect = argv[++i];
    }
    uint8_t *kernel = load(argv[1], &ksz);
    e.disk = load(argv[2], &e.disk_size);
    /* blitz86 needs the A20-on window (1 MiB + HMA); microDOS uses the first 1 MiB */
    uint8_t *memory = aligned_alloc(64, (B86_MEM_BYTES + 63u) & ~63u);
    if (!kernel || !e.disk || !memory) { fprintf(stderr, "cannot load inputs\n"); return 2; }
    memset(memory, 0, B86_MEM_BYTES);
    bb_live_set_enabled(!interp);

    md_dos2_system_init(&sys, memory, NULL);
    sys.boot.console.write = con_write;
    sys.boot.console.peek = con_peek;
    sys.boot.console.read = con_read;
    sys.boot.console.flush = con_flush;
    sys.boot.console.user = &e;
    sys.boot.disk.read = disk_read;
    sys.boot.disk.write = disk_write;
    sys.boot.disk.user = &e;
    sys.boot.disk.sector_size = 512u;
    sys.boot.disk.sector_count = (uint32_t)(e.disk_size / 512u);
    sys.boot.disk.writable = true;
    sys.boot.clock_days = 1162u;
    sys.boot.clock_hours = 12u;
    if (!md_dos2_system_start(&sys, kernel, ksz)) { fprintf(stderr, "bad MSDOS.SYS\n"); return 2; }

    MdStopReason stop = MD_STOP_NONE;
    clock_t t0 = clock();
    int done = 0;
    uint64_t next = 0; BbLiveStats pv; memset(&pv, 0, sizeof pv);
    uint64_t budget = getenv("BUDGET") ? strtoull(getenv("BUDGET"), 0, 0) : BUDGET;
    while (sys.runtime.instructions < budget) {
        stop = md_dos2_system_run(&sys, 100000u);
        if (stop != MD_STOP_NONE) break;
        if (sys.runtime.instructions >= next) {
            next += 10000000ull;
            BbLiveStats s; bb_live_get_stats(&s);
            fprintf(stderr, "[3db] insns=%lluM retired+%llu native+%llums tr+%llums blocks+%llu flushes+%llu step+%llu cond+%llu flags+%llu light+%llu smc+%llu rep+%llu disp+%llu fast+%llu syncs+%llu inval+%llu hooks+%llu slices+%llu\n",
              (unsigned long long)(sys.runtime.instructions/1000000), (unsigned long long)(s.retired-pv.retired),
              (unsigned long long)((s.native_us-pv.native_us)/1000), (unsigned long long)((s.translate_us-pv.translate_us)/1000),
              (unsigned long long)(s.blocks-pv.blocks), (unsigned long long)(s.flushes-pv.flushes),
              (unsigned long long)(s.rt_step-pv.rt_step), (unsigned long long)(s.rt_cond-pv.rt_cond), (unsigned long long)(s.rt_flags-pv.rt_flags),
              (unsigned long long)(s.rt_light-pv.rt_light), (unsigned long long)(s.rt_smc-pv.rt_smc), (unsigned long long)(s.rt_rep-pv.rt_rep),
              (unsigned long long)(s.dispatches-pv.dispatches), (unsigned long long)(s.fast_dispatches-pv.fast_dispatches),
              (unsigned long long)(s.page_syncs-pv.page_syncs), (unsigned long long)(s.page_invalidations-pv.page_invalidations),
              (unsigned long long)(s.hook_calls-pv.hook_calls), (unsigned long long)(s.slices-pv.slices));
            pv = s;
        }
    }
    double secs = (double)(clock() - t0) / CLOCKS_PER_SEC;
    e.out[e.len] = '\0';

    BbLiveStats s;
    bb_live_get_stats(&s);
    printf("\n[e2e] backend=%s instructions=%llu time=%.2fs stop=%s\n", interp ? "interp" : "blitz86",
           (unsigned long long)sys.runtime.instructions, secs, md_stop_reason_name(stop));
    printf("[e2e] blitz86 retired=%llu (%.1f%%) slices=%llu traps=%llu hooks=%llu page-syncs=%llu code-lines-changed=%llu blocks=%llu fail=%s\n",
           (unsigned long long)s.retired,
           sys.runtime.instructions ? 100.0 * (double)s.retired / (double)sys.runtime.instructions : 0.0,
           (unsigned long long)s.slices, (unsigned long long)s.traps, (unsigned long long)s.hook_calls,
           (unsigned long long)s.page_syncs, (unsigned long long)s.page_invalidations, (unsigned long long)bb_live_blocks(), bb_live_fail_reason());
    {
        extern struct B86Jit *bb_live_jit(void);
        struct B86Jit *jj = bb_live_jit();
        if (jj) {
            const B86JitStats *js = b86_jit_stats(jj);
            printf("[e2e] C round trips: step=%llu cond=%llu flags=%llu light=%llu smc=%llu rep=%llu  lookups-missed=%llu\n",
                   (unsigned long long)js->rt_step, (unsigned long long)js->rt_cond, (unsigned long long)js->rt_flags,
                   (unsigned long long)js->rt_light, (unsigned long long)js->rt_smc, (unsigned long long)js->rt_rep,
                   (unsigned long long)(js->dispatches - js->fast_dispatches));
            printf("[e2e] host-bytes=%llu guest-insns=%llu joins=%llu inner=%llu splits=%llu cold-runs=%llu cold-insns=%llu\n", (unsigned long long)js->host_bytes, (unsigned long long)js->guest_insns, (unsigned long long)js->joins, (unsigned long long)js->inner_branches, (unsigned long long)js->splits, (unsigned long long)js->cold_runs, (unsigned long long)js->cold_insns);
            printf("[e2e] jit blocks=%llu flushes=%llu smc-hits=%llu smc-inval=%llu chains=%llu dispatches=%llu helpers=%llu bytes/insn=%.1f\n",
                   (unsigned long long)js->blocks, (unsigned long long)js->flushes, (unsigned long long)js->smc_hits,
                   (unsigned long long)js->smc_invalidations, (unsigned long long)js->chains, (unsigned long long)js->dispatches,
                   (unsigned long long)js->helper_insns, js->guest_insns ? (double)js->host_bytes / (double)js->guest_insns : 0.0);
        }
    }
    printf("[e2e] time native=%llums (translate %llums) sync=%llums  flushes=%llu dispatches=%llu fast=%llu tr-pages=%llu\n",
           (unsigned long long)(s.native_us / 1000), (unsigned long long)(s.translate_us / 1000), (unsigned long long)(s.sync_us / 1000),
           (unsigned long long)s.flushes, (unsigned long long)s.dispatches, (unsigned long long)s.fast_dispatches, (unsigned long long)s.tr_pages);
#ifdef B86_HELPER_HISTO
    {
        extern uint64_t b86_helper_histo[256];
        uint64_t tot = 0; for (int i = 0; i < 256; ++i) tot += b86_helper_histo[i];
        printf("[e2e] helper executions %llu; top opcodes:", (unsigned long long)tot);
        for (int n = 0; n < 16; ++n) { int bi = 0; for (int i = 1; i < 256; ++i) if (b86_helper_histo[i] > b86_helper_histo[bi]) bi = i;
            if (!b86_helper_histo[bi]) break; printf(" %02X:%llu", bi, (unsigned long long)b86_helper_histo[bi]); b86_helper_histo[bi] = 0; }
        printf("\n");
        extern uint64_t b86_helper_histo2[32];
        printf("[e2e] D0/D1 by w,reg:"); for (int i = 0; i < 16; ++i) if (b86_helper_histo2[i]) printf(" w%d/%d:%llu", i / 8, i % 8, (unsigned long long)b86_helper_histo2[i]);
        printf("\n[e2e] F6/F7 by w,reg:"); for (int i = 16; i < 32; ++i) if (b86_helper_histo2[i]) printf(" w%d/%d:%llu", (i - 16) / 8, i % 8, (unsigned long long)b86_helper_histo2[i]);
        printf("\n");
    }
#endif
    return 0;
}
