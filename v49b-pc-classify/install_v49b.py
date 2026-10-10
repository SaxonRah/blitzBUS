#!/usr/bin/env python3
"""Guarded replacement of the existing v49 profiler header (complete file)."""
import argparse
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--blitzbus',type=Path,required=True)
a=p.add_mutually_exclusive_group(required=True)
a.add_argument('--check',action='store_true');a.add_argument('--apply',action='store_true');a.add_argument('--restore',action='store_true')
x=p.parse_args()
target=x.blitzbus/'src'/'bb_v49_pc.h'
source=Path(__file__).with_name('bb_v49_pc.h')
backup=target.with_name('bb_v49_pc.h.before_v49b')
try:
    if x.restore:
        if not backup.is_file():raise ValueError('no v49b backup')
        target.write_bytes(backup.read_bytes());print('RESTORED:',target)
    else:
        if not target.is_file():raise ValueError('missing existing v49 header')
        old=target.read_text();new=source.read_text()
        for marker in ('bb49_init(', 'bb49_report(', 'bb49_capture(', 'addeq r0, r0, #72'):
            if marker not in old:raise ValueError('existing header lacks '+marker)
        for marker in ('[bb-v49b-regions]', '[bb-v49b-rawpc]', 'bb49_region('):
            if marker not in new:raise ValueError('bundled header lacks '+marker)
        if x.check:print('CHECK PASS: expected FP-fixed v49 profiler header found; no changes')
        else:
            if backup.exists():raise ValueError('backup already exists; refusing overwrite')
            backup.write_bytes(target.read_bytes());target.write_bytes(source.read_bytes())
            print('INSTALLED:',target);print('BACKUP:',backup)
except Exception as e:p.exit(1,'ERROR: '+str(e)+'\n')
