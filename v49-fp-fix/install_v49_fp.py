#!/usr/bin/env python3
"""Guarded, rollbackable full header replacement for v49's FP frame handling."""
import argparse
import hashlib
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--blitzbus', type=Path, required=True)
a = p.add_mutually_exclusive_group(required=True)
a.add_argument('--check', action='store_true')
a.add_argument('--apply', action='store_true')
a.add_argument('--restore', action='store_true')
args = p.parse_args()
target = args.blitzbus / 'src' / 'bb_v49_pc.h'
source = Path(__file__).with_name('bb_v49_pc.h')
backup = target.with_name('bb_v49_pc.h.before_fp_fix')
try:
    if args.restore:
        if not backup.is_file(): raise ValueError('no backup available; nothing changed')
        target.write_bytes(backup.read_bytes())
        print('RESTORED:', target)
    else:
        if not target.is_file(): raise ValueError('missing existing v49 header')
        old = target.read_text()
        new = source.read_text()
        for check in ('bb49_init(', 'bb49_report(', 'tst lr, #0x10', 'beq 1f', 'b bb49_capture'):
            if check not in old: raise ValueError('unexpected existing header; expected: '+check)
        for check in ('addeq r0, r0, #72', 'tst lr, #0x10', 'b bb49_capture'):
            if check not in new: raise ValueError('replacement missing: '+check)
        if args.check: print('CHECK PASS: current v49 header identified; no changes made')
        else:
            if backup.exists(): raise ValueError('backup already exists; refusing to overwrite it')
            backup.write_bytes(target.read_bytes())
            target.write_bytes(source.read_bytes())
            print('INSTALLED:',target)
            print('BACKUP:',backup)
except Exception as ex:
    p.exit(1,'ERROR: '+str(ex)+'\n')
