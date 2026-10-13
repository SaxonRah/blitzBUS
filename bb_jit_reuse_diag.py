#!/usr/bin/env python3
"""Reversible low-overhead blitz86 JIT eviction/retranslation diagnostics.

Usage from C:\\blitzBUS:
    python bb_jit_reuse_diag.py apply
    python bb_jit_reuse_diag.py verify
    python bb_jit_reuse_diag.py restore

Edits local C:\\blitz86_v2\\src\\jit.c and C:\\blitzBUS\\src\\bb_live.c.
Never edits the installer, linker script, or SRAM/PSRAM allocations.
"""
import argparse
from pathlib import Path

MARK='BB_REUSE_DIAG_V1'

def read(p): return p.read_text(encoding='utf-8-sig')

def one(s,old,new,desc):
    n=s.count(old)
    if n!=1:raise RuntimeError(f'{desc}: expected exactly one source anchor, got {n}; no files changed')
    return s.replace(old,new,1)

def apply(root,blitz):
    jit=blitz/'src'/'jit.c'; live=root/'src'/'bb_live.c'
    if not jit.is_file() or not live.is_file():raise RuntimeError('Required source file missing')
    j=read(jit); l=read(live)
    if MARK in j or MARK in l:raise RuntimeError('Diagnostics already present or partly applied; verify or restore')
    jb=jit.with_name('jit.c.reuse-diag-baseline.bak');lb=live.with_name('bb_live.c.reuse-diag-baseline.bak')
    if jb.exists() or lb.exists():raise RuntimeError('Existing backup: refuse to overwrite')
    # 256 exact direct-mapped *guest key* slots, deliberately sampled only at
    # eviction and translation, never per native instruction or fast dispatch.
    diag='''/* BB_REUSE_DIAG_V1: evicted-entry recurrence, diagnostic only. */
static uint32_t bbdiag_evicted_keys[256];
static uint8_t bbdiag_evicted_valid[256];
static uint32_t bbdiag_evicted_total, bbdiag_retranslated, bbdiag_collision;
static uint32_t bbdiag_evicted_lost_chains;
static uint32_t bbdiag_slot(uint32_t key) { return (key ^ (key >> 13) ^ (key >> 22)) & 255u; }
static void bbdiag_evict(uint32_t key) {
    uint32_t s=bbdiag_slot(key);
    if (bbdiag_evicted_valid[s] && bbdiag_evicted_keys[s]!=key) ++bbdiag_collision;
    bbdiag_evicted_keys[s]=key;
    bbdiag_evicted_valid[s]=1;
    ++bbdiag_evicted_total;
}
static void bbdiag_translate(uint32_t key) {
    uint32_t s=bbdiag_slot(key);
    if (bbdiag_evicted_valid[s] && bbdiag_evicted_keys[s]==key) {
        ++bbdiag_retranslated;
        bbdiag_evicted_valid[s]=0;
    }
}
void b86_jit_reuse_diag(uint32_t *evicted, uint32_t *retranslated,
                        uint32_t *collisions, uint32_t *broken_patches) {
    if(evicted)*evicted=bbdiag_evicted_total;
    if(retranslated)*retranslated=bbdiag_retranslated;
    if(collisions)*collisions=bbdiag_collision;
    if(broken_patches)*broken_patches=bbdiag_evicted_lost_chains;
}
'''
    j=one(j,'/* Reclaim the code of every block that starts in [lo, hi).',diag+'\n/* Reclaim the code of every block that starts in [lo, hi).','insert helper')
    j=one(j,'        if (!b->dead) { kill_block(j, i); j->st.smc_invalidations--; }',
          '        if (!b->dead) {\n            if (!b->spec) bbdiag_evict(b->key);\n            kill_block(j, i); j->st.smc_invalidations--;\n        }', 'eviction mark')
    j=one(j,'                j->st.unchains++;\n                continue;',
          '                j->st.unchains++;\n                ++bbdiag_evicted_lost_chains;\n                continue;', 'unchain diagnostic')
    j=one(j,'    j->st.blocks++;\n    j->st.guest_insns +=',
          '    if (!npre) bbdiag_translate(b->key);\n    j->st.blocks++;\n    j->st.guest_insns +=', 'translation diagnostic')
    # Report from known-working periodic reporting path in blitzBUS.
    anchor='    printf("[bb-jit] native-ms='
    report='''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    /* BB_REUSE_DIAG_V1: summary at existing periodic JIT report cadence. */
    { uint32_t e=0,rt=0,col=0,br=0;
      extern void b86_jit_reuse_diag(uint32_t *,uint32_t *,uint32_t *,uint32_t *);
      b86_jit_reuse_diag(&e,&rt,&col,&br);
      printf("[bb-reuse] evicted-keys=%lu retranslated=%lu slot-collisions=%lu broken-patches=%lu\\n",
        (unsigned long)e,(unsigned long)rt,(unsigned long)col,(unsigned long)br);
    }
#endif
'''
    l=one(l,anchor,report+anchor,'periodic reporting')
    # Validate original signatures before mutating either file.
    jb.write_bytes(jit.read_bytes());lb.write_bytes(live.read_bytes())
    try:
        jit.write_text(j,encoding='utf-8');live.write_text(l,encoding='utf-8')
    except Exception:
        jit.write_bytes(jb.read_bytes());live.write_bytes(lb.read_bytes());raise
    print('Installed JIT reuse diagnostics. Rebuild with BB_HOT_THRESHOLD=32.')
    print('Backups:',jb,lb)
    print('Approximate 1.3 KiB extra JIT static RAM; no PSRAM allocation resized.')

def restore(root,blitz):
    paths=[blitz/'src'/'jit.c',root/'src'/'bb_live.c']
    for p in paths:
        bk=p.with_name(p.name+'.reuse-diag-baseline.bak')
        if not bk.exists() or MARK not in read(p):raise RuntimeError(f'Cannot safely restore {p}: missing backup or marker')
    for p in paths:
        bk=p.with_name(p.name+'.reuse-diag-baseline.bak')
        p.write_bytes(bk.read_bytes());bk.unlink()
    print('Restored source files. Rebuild to remove instrumentation.')

def verify(root,blitz):
    for p in [blitz/'src'/'jit.c',root/'src'/'bb_live.c']:
        s=read(p);print(p,'installed' if MARK in s else 'not installed')

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action',choices=['apply','restore','verify'])
    ap.add_argument('--root',default=r'C:\blitzBUS')
    ap.add_argument('--blitz',default=r'C:\blitz86_v2')
    a=ap.parse_args()
    try: {'apply':apply,'restore':restore,'verify':verify}[a.action](Path(a.root),Path(a.blitz))
    except Exception as e:ap.exit(1,'ERROR: '+str(e)+'\n')
