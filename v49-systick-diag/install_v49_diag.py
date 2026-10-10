#!/usr/bin/env python3
"""v49 SysTick diagnostic header: guarded, backup and restore; complete files only."""
from pathlib import Path
import argparse,sys
p=argparse.ArgumentParser()
p.add_argument('--blitzbus',required=True)
a=p.add_mutually_exclusive_group(required=True)
a.add_argument('--check',action='store_true')
a.add_argument('--apply',action='store_true')
a.add_argument('--restore',action='store_true')
o=p.parse_args()
dest=Path(o.blitzbus)/'src'/'bb_v49_pc.h'
bak=dest.with_name(dest.name+'.before_v49_diag')
source=Path(__file__).with_name('bb_v49_pc.h')
try:
 if o.restore:
  if not bak.is_file():raise ValueError('missing backup '+str(bak))
  dest.write_bytes(bak.read_bytes());print('RESTORED',dest);sys.exit(0)
 if not dest.is_file():raise ValueError('v49 header missing: '+str(dest))
 existing=dest.read_text(encoding='utf-8')
 if '[bb-v49-systick-diag]' in existing:raise ValueError('diagnostics already installed')
 if 'static void bb49_report(struct B86Jit *jit)' not in existing or '[bb-v49-pc]' not in existing or 'bb49_handler' not in existing:raise ValueError('unexpected header; abort')
 new=source.read_text(encoding='utf-8')
 if '[bb-v49-systick-diag]' not in new or 'bb49_report' not in new:raise ValueError('bad replacement header')
 if o.check:
  print('CHECK PASS: v49 header identified; no changes');sys.exit(0)
 if bak.exists():raise ValueError('backup exists, refusing overwrite: '+str(bak))
 bak.write_bytes(dest.read_bytes())
 dest.write_bytes(source.read_bytes())
 print('APPLIED',dest,'\nBACKUP',bak)
except (OSError,ValueError) as e:
 print('FAILED:',e,file=sys.stderr);sys.exit(1)
