#!/usr/bin/env python3
"""Read-only blitzBUS DOS 6.22 raw-log audit and last-screen reconstruction.
Usage: python bb_dos622_log_audit.py C:\\blitzBUS\\logs\\bb-live-...-console.txt
Option: --screen-output last_dos_screen.txt
No edits to input log, firmware, disk image or repository.
"""
import argparse
import collections
import json
import re
from pathlib import Path

ROW=re.compile(r'^\[bb622-screen\] row=(\d\d) (?:\(cleared\)|\|(.*)\|)$')
TAG=re.compile(r'^\[([^]]+)\]')
DANGER=re.compile(r'\[bb622-missing-bios\]|\[bb622-hddv2\] FAIL|\[(?:bb622-hdd|bb-sd-b)\] (?:READ|WRITE) (?:FAIL|ERROR)|guest stopped:|Pico flashing failed|Live target build failed')

def analyze(s):
    screen=['']*25
    tags=collections.Counter()
    errors=[]
    checkpoints=[]
    updates=0
    for ln in s.splitlines():
        m=ROW.match(ln)
        if m:
            idx=int(m.group(1))
            if idx<25:
                screen[idx]=m.group(2) or ''
                updates+=1
        t=TAG.match(ln)
        if t:tags[t.group(1)]+=1
        if DANGER.search(ln):
            if len(errors)<50:errors.append(ln)
        if any(w in ln for w in ('[bb622-hdd] BIOS 80h mounted','[bb622-floppyb] BIOS DL=01','[bb-sd-b] read disk=1','MS-DOS Version 6.22','|B:\\>','[bb622-lcdclear]')):
            if len(checkpoints)<35:checkpoints.append(ln)
    return dict(screen=screen,updates=updates,top_tags=tags.most_common(24),errors=errors,checkpoints=checkpoints)

def render_screen(lines):return '\n'.join((line[:80]).ljust(80) for line in lines)+'\n'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('log',type=Path)
    p.add_argument('--screen-output',type=Path)
    p.add_argument('--json-output',type=Path)
    args=p.parse_args()
    a=analyze(args.log.read_text(encoding='utf-8-sig',errors='replace'))
    print('=== Last observed DOS 80x25 screen (not a current live frame) ===')
    print(render_screen(a['screen']),end='')
    print('\n=== Significant events / errors ===')
    for e in a['errors']:print(e)
    print('\n=== Frequent diagnostic tags ===')
    for t,n in a['top_tags']:print(f'{t:<24} {n:>5}')
    print('\nDOS screen row updates:',a['updates'])
    if args.screen_output:
        args.screen_output.write_text(render_screen(a['screen']),encoding='utf-8')
        print('WROTE screen:',args.screen_output)
    if args.json_output:
        args.json_output.write_text(json.dumps(a,indent=2)+'\n',encoding='utf-8')
        print('WROTE JSON audit:',args.json_output)

if __name__=='__main__':main()
