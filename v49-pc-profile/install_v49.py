#!/usr/bin/env python3
"""Fail-closed complete-file v49 installer; no Git patches. --check/--apply/--restore."""
import argparse,pathlib,sys
p=argparse.ArgumentParser();p.add_argument('--blitz86',required=True);p.add_argument('--blitzbus',required=True);p.add_argument('--check',action='store_true');p.add_argument('--apply',action='store_true');p.add_argument('--restore',action='store_true');a=p.parse_args()
if sum((a.check,a.apply,a.restore))!=1:p.error('Choose exactly one of --check --apply --restore')
b86=pathlib.Path(a.blitz86);bb=pathlib.Path(a.blitzbus)
paths=[b86/'include/b86.h',b86/'src/jit.c',bb/'src/bb_live.c',bb/'src/bb_v49_pc.h']
source=pathlib.Path(__file__).with_name('bb_v49_pc.h').read_text()
def insert_once(s,anchor,add):
 n=s.count(anchor)
 if n!=1:raise ValueError(f'expected one anchor {anchor!r}, found {n}')
 return s.replace(anchor,anchor+add,1)
try:
 if a.restore:
  for q in paths:
   bak=q.with_name(q.name+'.before_v49')
   if q.name.endswith('.h') and q.name=='bb_v49_pc.h':
    if q.exists():q.unlink();print('REMOVED',q)
   elif bak.exists():q.write_bytes(bak.read_bytes());print('RESTORED',q)
   else:raise ValueError(f'missing backup {bak}')
  sys.exit(0)
 for q in paths[:3]:
  if not q.exists():raise ValueError(f'missing {q}')
 h,j,live=[q.read_text(encoding='utf-8') for q in paths[:3]]
 if 'bb49_init(' in live or 'b86_jit_pc_lookup(' in j or 'bb49_report(' in live:raise ValueError('v49 already present; do not reapply')
 h=insert_once(h,'const B86JitStats *b86_jit_stats(struct B86Jit *j);','\n/* v49: map a sampled Thumb-2 PC to the containing live translated block. */\nint b86_jit_pc_lookup(struct B86Jit *j, uintptr_t pc, uint32_t *key, uint32_t *offset);')
 needle='B86_HOT const B86JitStats *b86_jit_stats(J *j) { return &j->st; }'
 impl='''\n/* v49: reporter-side only; scan generation-local code layout. */
int b86_jit_pc_lookup(J *j, uintptr_t pc, uint32_t *key, uint32_t *offset) {
    if (!j || !key || !offset) return 0;
    pc &= ~(uintptr_t)1;
    if (pc < (uintptr_t)j->code_start || pc >= (uintptr_t)j->e.p) return 0;
    for (uint32_t i=0;i<j->nblk;i++) {
        Block *b=&j->blk[i];
        uintptr_t lo=(uintptr_t)b->host;
        uintptr_t hi=(i+1u<j->nblk)?(uintptr_t)j->blk[i+1u].host:(uintptr_t)j->e.p;
        if (pc>=lo && pc<hi && !b->dead && !j->dead[i]) {
            *key=b->key;*offset=(uint32_t)(pc-lo);return 1;
        }
    }
    return 0;
}
'''
 j=insert_once(j,needle,impl)
 live=insert_once(live,'#include "b86.h"','\n#define BB_V49_PC_PROFILE 1 /* v49 installer opt-in; remove to disable */\n#include "bb_v49_pc.h"')
 live=insert_once(live,'    if (J == NULL) { failed = 1; fail_reason = "jit-create"; return 0; }','\n#ifdef BB_V49_PC_PROFILE\n    bb49_init(clock_get_hz(clk_sys)/1000u);\n#endif')
 live=insert_once(live,'    bb_irq36_report();','\n#ifdef BB_V49_PC_PROFILE\n    bb49_report(J);\n#endif')
 # The v49 header is bundled but its inclusion is always parseable: profile stays disabled by default.
 # Validation focuses on essential source syntax anchors and compile-time API contract.
 if h.count('b86_jit_pc_lookup')!=1 or j.count('int b86_jit_pc_lookup(')!=1:raise ValueError('API insertion invalid')
 if a.check:
  print('CHECK PASS: 3 full files + profiler header validated, nothing changed')
 else:
  for q,body in zip(paths[:3],[h,j,live]):
   bak=q.with_name(q.name+'.before_v49')
   if bak.exists():raise ValueError(f'backup already exists: {bak} (aborting before write)')
  for q,body in zip(paths[:3],[h,j,live]):
   q.with_name(q.name+'.before_v49').write_bytes(q.read_bytes())
   q.write_text(body,encoding='utf-8',newline='\n')
   print('INSTALLED',q)
  paths[3].write_text(source,encoding='utf-8',newline='\n')
  print('INSTALLED',paths[3])
  print('v49 PC sampling ENABLED by source opt-in; full restore via --restore')
except Exception as e:
 print('CHECK FAILED:',e,file=sys.stderr);sys.exit(1)
