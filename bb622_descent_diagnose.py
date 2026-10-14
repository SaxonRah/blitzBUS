#!/usr/bin/env python3
"""Read-only Descent disk-swap and guest-progress analyzer for blitzBUS raw logs.

python bb622_descent_diagnose.py --latest --root C:\\blitzBUS
or python bb622_descent_diagnose.py PATH_TO_LOG
"""
from __future__ import annotations
import argparse,re
from pathlib import Path

def run():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('file',nargs='?');a.add_argument('--latest',action='store_true');a.add_argument('--root',default='.')
    args=a.parse_args()
    if args.latest:
        logs=sorted((Path(args.root)/'logs').glob('bb-live-*-console.txt'),key=lambda f:f.stat().st_mtime,reverse=True)
        if not logs:raise SystemExit('No matching capture in logs directory')
        log=logs[0]
    else:
        if not args.file:raise SystemExit('Supply a log path, or --latest')
        log=Path(args.file)
    data=log.read_text(encoding='utf-8',errors='replace').splitlines()
    patt=re.compile(r'\[(?:bb622-swap|bb622-bmedia|bb-sd-b|bb622-hddv2|bb622-hostswap|bb622-ackhost|bb622-boot|EMU ALERT|bb622-watch|microDOS|bb622-irq0-ab)\]|(?:guest stopped|READ ERROR|WRITE FAIL|FAIL|HardFault)',re.I)
    events=[f'{i:05d}: {line}' for i,line in enumerate(data,1) if patt.search(line)]
    outfile=log.with_name(log.stem+'-descent-swaps.txt')
    section=['BLITZBUS Descent swap diagnosis','Source: '+str(log),'Events: '+str(len(events)),'','LAST 200 MATCHING EVENTS:']+events[-200:]
    change=[(i,x) for i,x in enumerate(data) if re.search(r'\[bb622-swap\] B:\d+ OK',x)]
    section+=['','LATEST B: CHANGE:']
    if change:
        pos,x=change[-1];section.append(f'{pos+1}: {x}')
        future=data[pos+1:]
        ah=[f'{pos+2+i}: {v}' for i,v in enumerate(future) if '[bb622-bmedia]' in v and 'AH=16' in v]
        reads=[f'{pos+2+i}: {v}' for i,v in enumerate(future) if 'B first new-image read' in v]
        section+=['BIOS CHANGE QUERIES AFTER SWAP:']+(ah[:12] or ['(none observed)'])
        section+=['FIRST PHYSICAL READ AFTER SWAP:']+(reads[:3] or ['(none observed)'])
    else:section.append('No successful B change found in this log.')
    watches=[(int(n),int(d),i) for i,v in enumerate(data) if (m:=re.search(r'\[bb622-watch\].*?insns=(\d+) delta=(\d+)',v)) for n,d in [m.groups()]]
    section+=['','CPU PROGRESS:']
    if watches:
        section.append('Latest sampled instructions: '+str(watches[-1][0]))
        section.append('Latest delta: '+str(watches[-1][1]))
        section.append('Last 5 samples: '+', '.join(str(n)+'(+'+str(d)+')' for n,d,_ in watches[-5:]))
    else:section.append('No [bb622-watch] samples available')
    section+=['','HOW TO INTERPRET:','B:2 OK only proves host-side mount, not a guest disk read.',
      'B first new-image read confirms guest BIOS accessed the mounted image.',
      'No AH=16 is not definitive: DOS may detect change using another path.',
      'Continuously increasing instruction counts can indicate an idle loop, not necessarily useful progress.',
      'IRQ0 remains suppressed in current DOS6 configuration and could affect software that waits for timer ticks.']
    outfile.write_text('\n'.join(section)+'\n',encoding='utf-8')
    print('REPORT:',outfile)
    print('\n'.join(section[-15:]))
if __name__=='__main__':run()
