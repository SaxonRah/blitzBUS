#!/usr/bin/env python3
"""blitz86/blitzBUS v48 sampled JIT entry profiler. Complete-file guarded installer."""
import argparse, pathlib, shutil, re, sys

HEADER_DECL = '''/* v48 sampled native dispatch profiler (diagnostic, approximate). */
void b86_jit_hot_report(struct B86Jit *j);
'''

JIT_PROF = r'''/* v48: sparse sampled native entry timing.  A sample measures the complete
 * native entry, potentially including chained successors. It is NOT a PC
 * interrupt sampler and MUST NOT be interpreted as exclusive block CPU time.
 * Only one in 256 outer dispatches incurs B86_NOW() overhead.
 * Fixed-size table resides in the JIT metadata allocator (PSRAM on Pico).
 */
#ifdef B86_NOW
typedef struct B86HotSample {
    uint32_t key;
    uint32_t count;
    uint64_t us;
    uint32_t max_us;
} B86HotSample;
#define B86_HOT_SLOTS 256u
static uint64_t b86_v48_polls;
static B86HotSample *b86_v48_samples;
static void b86_v48_record(uint32_t key, uint64_t delta) {
    if (!b86_v48_samples) return;
    unsigned p = (key * 2654435761u) >> 24;
    /* Direct-mapped replacement: collisions are explicitly identified. */
    B86HotSample *s = &b86_v48_samples[p];
    if (!s->count || s->key != key) {
        s->key = key; s->count = 0; s->us = 0; s->max_us = 0;
    }
    s->count++;
    s->us += delta;
    if (delta > s->max_us) s->max_us = (uint32_t)(delta > UINT32_MAX ? UINT32_MAX : delta);
}
#endif
B86_HOT void b86_jit_hot_report(struct B86Jit *j) {
#ifdef B86_NOW
    (void)j;
    if (!b86_v48_samples) return;
    printf("[bb-v48-hot] sampled-dispatches=%llu divisor=256 slots=256 units=us (includes-chained-code)\n", (unsigned long long)(b86_v48_polls >> 8));
    /* top 12 nonzero entries by cumulative sampled time; no sorting memory */
    uint8_t selected[B86_HOT_SLOTS] = {0};
    for (unsigned rank = 0; rank < 12; ++rank) {
        unsigned best = B86_HOT_SLOTS;
        for (unsigned i = 0; i < B86_HOT_SLOTS; ++i)
            if (!selected[i] && b86_v48_samples[i].count &&
                (best == B86_HOT_SLOTS || b86_v48_samples[i].us > b86_v48_samples[best].us)) best = i;
        if (best == B86_HOT_SLOTS) break;
        selected[best] = 1;
        const B86HotSample *s = &b86_v48_samples[best];
        printf("[bb-v48-hot-entry] rank=%u cs=%04X ip=%04X samples=%lu total-us=%llu max-us=%lu\n",
            rank + 1, (unsigned)(s->key >> 16), (unsigned)(s->key & 0xFFFFu),
            (unsigned long)s->count, (unsigned long long)s->us, (unsigned long)s->max_us);
    }
#else
    (void)j;
#endif
}
'''

def transform(header, jit, bus):
    # Keep existing version and avoid double install.
    if 'b86_jit_hot_report' in header or 'b86_v48_record' in jit or '[bb-v48-hot]' in bus:
        raise ValueError('v48 already applied or files partially modified; restore backup first')
    anchor = 'const B86JitStats *b86_jit_stats(struct B86Jit *j);'
    if header.count(anchor)!=1: raise ValueError('b86.h stats prototype not found exactly once')
    header=header.replace(anchor,anchor+'\n'+HEADER_DECL)
    if jit.count('typedef struct Block {')!=1: raise ValueError('Block anchor missing')
    jit=jit.replace('typedef struct Block {',JIT_PROF+'\ntypedef struct Block {',1)
    if jit.count('        int r = j->enter(c, be_code_ptr(host));')!=1: raise ValueError('native entry anchor missing')
    jit=jit.replace('        int r = j->enter(c, be_code_ptr(host));', '''#ifdef B86_NOW
        uint64_t bb48_start = 0;
        int bb48_sample = ((++b86_v48_polls & 255u) == 0u);
        if (bb48_sample) {
            if (!b86_v48_samples) b86_v48_samples = B86_CALLOC(B86_HOT_SLOTS, sizeof *b86_v48_samples);
            bb48_start = B86_NOW();
        }
#endif
        int r = j->enter(c, be_code_ptr(host));
#ifdef B86_NOW
        if (bb48_sample) b86_v48_record(key, B86_NOW() - bb48_start);
#endif''',1)
    if bus.count('    bb_v33_jit_line();')!=1: raise ValueError('blitzBUS stats hook missing')
    bus=bus.replace('    bb_v33_jit_line();','    bb_v33_jit_line();\n    b86_jit_hot_report(J);',1)
    return header,jit,bus

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--blitz86',default=r'C:\blitz86_v2')
    p.add_argument('--blitzbus',default=r'C:\blitzBUS')
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true');group.add_argument('--apply',action='store_true');group.add_argument('--restore',action='store_true')
    a=p.parse_args()
    files=[pathlib.Path(a.blitz86)/'include/b86.h',pathlib.Path(a.blitz86)/'src/jit.c',pathlib.Path(a.blitzbus)/'src/bb_live.c']
    for f in files:
        if not f.exists(): raise SystemExit('MISSING: '+str(f))
    if a.restore:
        for f in files:
            b=f.with_name(f.name+'.before_v48')
            if not b.exists(): raise SystemExit('Missing backup: '+str(b))
        for f in files: shutil.copy2(f.with_name(f.name+'.before_v48'),f)
        print('RESTORED v48 backups');return
    try: new=transform(*(f.read_text(encoding='utf-8') for f in files))
    except ValueError as e: raise SystemExit('CHECK FAILED: '+str(e))
    if a.check:
        print('CHECK PASS: all three source anchors verified, no files changed');return
    for f in files:
        b=f.with_name(f.name+'.before_v48')
        if b.exists(): raise SystemExit('Backup already exists: '+str(b))
    for f,n in zip(files,new):
        shutil.copy2(f,f.with_name(f.name+'.before_v48'))
        f.write_text(n,encoding='utf-8')
        print('INSTALLED '+str(f))
    print('v48 installed; compile/flash still required')
if __name__=='__main__':main()
