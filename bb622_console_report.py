#!/usr/bin/env python3
"""Read-only blitzBUS log -> copyable DOS 80x25 + events + timeline.
usage: python bb622_console_report.py [path/to/console.txt | --latest] [--out PATH]
"""
from __future__ import annotations
import re,sys,argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CELLS=re.compile(r'^\[bb622-cells\] row=(\d\d) \|([a-fA-F0-9]{320})\|')
ROW=re.compile(r'^\[bb622-screen\] row=(\d\d) (?:\|(.*?)\||\(cleared\))')
WATCH=re.compile(r'^\[bb622-watch\].*?cs:ip=([0-9A-Fa-f]+:[0-9A-Fa-f]+).*?insns=(\d+).*?delta=(\d+)')
ALERT=re.compile(r'\[bb622-(?:missing-bios|hddv2|swap)|\[bb-sd-b\]|\[bb-dos622\].*ERROR|\[microDOS\] guest stopped|\[blitzBUS\] FAIL|\[bb-v51-fault\]|\[bb-v42-diag\]|\[bb622-boot\]|\[bb622-hdd\]')
HDR='# blitzBUS DOS 6.22 forensic report\n'

def analyze(data:str):
    rows=[' '*80 for _ in range(25)]; attrs=[[7]*80 for _ in range(25)]
    changes=0; color_rows=0; events=[]; watches=[]; snapshots=[]
    for n,line in enumerate(data.splitlines(),1):
        m=CELLS.match(line)
        if m:
            idx=int(m.group(1)); blob=bytes.fromhex(m.group(2))
            if idx<25:
                rows[idx]=bytes((blob[2*i] if blob[2*i]>=32 else 32) for i in range(80)).decode('cp437')
                attrs[idx]=[blob[2*i+1] for i in range(80)]
                changes+=1;color_rows+=1
            continue
        m=ROW.match(line)
        if m:
            idx=int(m.group(1))
            if idx<25 and not color_rows:
                rows[idx]=(m.group(2) or '').ljust(80)[:80];changes+=1
            continue
        m=WATCH.match(line)
        if m:watches.append((n,m.group(1),int(m.group(2)),int(m.group(3))))
        if ALERT.search(line):events.append((n,line[:600]))
    flat='\n'.join(f'{i:02d} |{r.rstrip()}|' for i,r in enumerate(rows))
    progress='No instruction samples'
    if len(watches)>=2:
        d=watches[-1][2]-watches[-2][2]
        progress=f'Latest guest instruction delta: {d:,} (samples at log lines {watches[-2][0]}, {watches[-1][0]})'
    return {'rows':rows,'attrs':attrs,'events':events,'watches':watches,'changes':changes,'color_rows':color_rows,'progress':progress,'flat':flat}

def newest(root:Path):
    logs=list((root/'logs').glob('bb-live-*-console.txt'))
    if not logs:raise ValueError('No raw bb-live console logs in '+str(root/'logs'))
    return max(logs,key=lambda p:p.stat().st_mtime)

def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('log',nargs='?',help='Raw console capture, defaults to most recent in C:\\blitzBUS\\logs')
    p.add_argument('--latest',action='store_true')
    p.add_argument('--out',help='Output prefix; default: same directory as log')
    p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args()
    src=Path(a.log) if a.log else newest(a.root)
    if not src.is_file():p.error('Missing console log '+str(src))
    results=analyze(src.read_text(encoding='utf8',errors='replace'))
    dest=Path(a.out) if a.out else src.with_suffix('')
    dest.parent.mkdir(parents=True,exist_ok=True)
    screen=dest.with_name(dest.name+'-screen.txt')
    events=dest.with_name(dest.name+'-events.txt')
    timeline=dest.with_name(dest.name+'-watch.txt')
    screen.write_text(HDR+f'Source: {src}\n{results["progress"]}\n\n'+results['flat']+'\n',encoding='utf-8')
    events.write_text(HDR+f'Source: {src}\n\n'+ '\n'.join(f'log {n}: {line}' for n,line in results['events'])+'\n',encoding='utf-8')
    timeline.write_text('log_line\tcs_ip\tinsns\tdelta\n'+'\n'.join('\t'.join(map(str,row)) for row in results['watches'])+'\n',encoding='utf-8')
    print('SCREEN:',screen,'\nEVENTS:',events,'\nCPU:',timeline)
    print('Screen updates:',results['changes'],'| Color rows:',results['color_rows'],'| Events:',len(results['events']))
    print(results['progress'])

if __name__=='__main__':cli()
