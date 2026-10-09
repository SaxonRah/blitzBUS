#!/usr/bin/env python3
"""v37: install the complete IRQ header, retaining an on-disk rollback copy."""
import argparse,hashlib,pathlib,shutil

def main():
 p=argparse.ArgumentParser();p.add_argument('repo',type=pathlib.Path)
 a=p.add_mutually_exclusive_group(required=True);a.add_argument('--check',action='store_true');a.add_argument('--apply',action='store_true');a.add_argument('--restore',action='store_true')
 x=p.parse_args();target=x.repo/'src'/'bb_irq.h';backup=x.repo/'src'/'bb_irq.h.before_v37';replacement=pathlib.Path(__file__).with_name('bb_irq.h')
 if x.restore:
  if not backup.is_file():p.error('v37 backup not found')
  shutil.copy2(backup,target);print('RESTORED:',target);return
 if not target.is_file():p.error('v36 src/bb_irq.h not found')
 old=target.read_text(encoding='utf8')
 if 'bb_v37_irq_report' in old:p.error('v37 appears already installed')
 if 'bb_irq36_dispatch' not in old or 'bb_irq36_report' not in old or 'bb_irq36.eois++' not in old:p.error('unexpected v36 header; no changes')
 if not replacement.is_file():p.error('replacement header missing')
 new=replacement.read_text(encoding='utf8')
 for token in ('bb_v37_poll_begin();','bb_v37_poll_end();','bb_v37_record_eoi();','bb_v37_irq_report();'):
  if token not in new:p.error('incomplete replacement')
 if x.check:print('CHECK PASS: v36 header found; v37 replacement validated; no changes');return
 if backup.exists():p.error('backup already exists; refusing to overwrite')
 shutil.copy2(target,backup);shutil.copy2(replacement,target)
 print('APPLIED: src/bb_irq.h (complete file); backup:',backup)
if __name__=='__main__':main()
