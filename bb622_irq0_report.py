#!/usr/bin/env python3
"""Read-only event and CPU analysis for blitzBUS one-shot IRQ0 trial."""
from __future__ import annotations
import argparse,pathlib,re,sys,time

WATCH=re.compile(r'^\[bb622-watch\].*$',re.M)
EVENT=re.compile(r'^\[bb622-irqtrial\] (ARMED|WAIT|TIMEOUT|DELIVERED)[^\r\n]*',re.M)
PIC=re.compile(r'^\[bb622-picprobe\] IN20[^\r\n]*',re.M)
DISK=re.compile(r'^\[(?:bb-sd-b|bb622-bmedia|bb622-hddv2|bb622-swap)\][^\r\n]*',re.M)


def f(line,key):
    m=re.search(r'(?:^|\s)'+re.escape(key)+r'=([0-9A-Fa-f]+)',line)
    return m.group(1) if m else None

def summarize(s):
    events=list(EVENT.finditer(s))
    print('IRQ0 ONE-SHOT TRIAL')
    print('===================')
    if not events:
        print('NO ARM EVENT FOUND. Confirm you are using bb_live_run_dos622_irqtrial.ps1 and a newly flashed firmware.')
        return
    arm=next((m for m in reversed(events) if m.group(1)=='ARMED'),None)
    if arm is None:
        print('No ARM found in current raw log; there may only be a prior event.')
        return
    tail=s[arm.start():]
    es=list(EVENT.finditer(tail))
    watches=list(WATCH.finditer(tail))
    pic=list(PIC.finditer(tail))
    disks=list(DISK.finditer(tail))
    for e in es:print(e.group(0))
    print(f'Watchdog samples after ARM: {len(watches)}')
    if watches:
        first,last=watches[0].group(0),watches[-1].group(0)
        print('First watch:',first)
        print('Last watch: ',last)
        for k in ('insns','bios13','other','ivt'):
            a,b=f(first,k),f(last,k)
            if a is not None and b is not None:
                print(f'{k} delta: +{int(b)-int(a):,}')
    print(f'PIC reads after ARM: {len(pic)}; disk/media events: {len(disks)}')
    for m in disks[-8:]:print(m.group(0))
    if any(e.group(1)=='DELIVERED' for e in es):
        print('RESULT: one guest IRQ0 was delivered. Check DOS progress and guest integrity before arming another.')
    elif any(e.group(1)=='TIMEOUT' for e in es):
        print('RESULT: no legal IRQ delivery boundary was observed within eight seconds. Inspect IF blocked vs masked counters; do not force an interrupt.')
    else:
        print('RESULT: armed; still awaiting delivery or timeout. Wait a few seconds and rerun report.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parent)
    p.add_argument('--log',type=pathlib.Path)
    p.add_argument('--wait',type=int,default=0)
    args=p.parse_args()
    if args.wait<0 or args.wait>20:p.error('wait seconds must be 0..20')
    if args.wait:time.sleep(args.wait)
    path=args.log
    if path is None:
        options=list((args.root/'logs').glob('bb-live-*-console.txt'))
        if not options:print('ERROR: no logs',file=sys.stderr);return 1
        path=max(options,key=lambda q:(q.stat().st_mtime_ns,q.name))
    print('RAW LOG:',path)
    summarize(path.read_bytes().decode('utf-8',errors='replace'))
    return 0
if __name__=='__main__':sys.exit(main())
