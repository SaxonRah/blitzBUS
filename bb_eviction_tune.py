#!/usr/bin/env python3
"""Reversible blitzBUS JIT eviction tuning. Save beside C:\\blitzBUS\\scripts.
Commands: apply, restore, run [--profiles ...], summary.
Does not change blitz86 source, PSRAM layout, or SRAM allocations.
"""
import argparse, csv, datetime, os, re, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
INSTALL = ROOT/'scripts'/'install_live.py'
BACKUP = ROOT/'scripts'/'install_live.py.eviction-ab-backup'
CSV = ROOT/'logs'/'bb-eviction-ab.csv'
MARK = '# BB_EVICTION_AB_V1'
PROFILES = {'control': (4096,2048), 'small': (2048,2048), 'large': (8192,2048), 'room4': (4096,4096)}
FIELDS = ['date','profile','chunk','room','score','render_ok','log','reports','evictions','evicted','unchains','retries','xip_miss','native_miss','meta_used','meta_failures']

def source(): return INSTALL.read_text(encoding='utf-8-sig')

def apply():
    s=source()
    if MARK in s:
        print('Already applied');return
    if BACKUP.exists(): raise ValueError('Old backup exists, refusing to overwrite it')
    anchor='    B86_MAXB=2048 B86_MAP_BITS=12 B86_FAST_BITS=10'
    env_anchor=re.search(r'^    hot=os\.environ\.get\("BB_HOT_THRESHOLD","(?:32|64)"\)',s,re.M)
    if s.count(anchor)!=1 or not env_anchor: raise ValueError('Installer anchors changed; nothing modified')
    # Insert Python values in the existing installer's function body, before CMake generation.
    vars='''    # BB_EVICTION_AB_V1: compiler parameters, no runtime overhead.
    eviction_chunk=int(os.environ.get('BB_EVICT_CHUNK','4096'))
    eviction_room=int(os.environ.get('BB_EVICT_ROOM','2048'))
    if eviction_chunk not in (2048,4096,8192):
        raise SystemExit('BB_EVICT_CHUNK must be 2048,4096,8192')
    if eviction_room not in (2048,4096):
        raise SystemExit('BB_EVICT_ROOM must be 2048,4096')
'''
    s=s[:env_anchor.start()]+vars+s[env_anchor.start():]
    s=s.replace(anchor,anchor+' B86_EVICT_CHUNK={eviction_chunk}u B86_EVICT_ROOM={eviction_room}u',1)
    BACKUP.write_bytes(INSTALL.read_bytes())
    INSTALL.write_text(s,encoding='utf-8')
    print('Applied. Backup:',BACKUP)
    print('Preserved existing PSRAM disk-section reordering modification.')

def restore():
    if not BACKUP.exists() or MARK not in source(): raise ValueError('Cannot safely restore; missing backup or marker')
    INSTALL.write_bytes(BACKUP.read_bytes()); BACKUP.unlink()
    print('Restored installer before eviction experiment; rebuild firmware to restore original.')

def parse_log(p):
    raw=p.read_text(encoding='utf-8',errors='replace')
    logs=re.findall(r'(?m)^\[bb-jit\][^\r\n]*',raw)
    def counter(name):
        pattern=re.compile(r'(?<![\w-])'+re.escape(name)+r'=(\d+)')
        return sum(int(m.group(1)) for line in logs if (m:=pattern.search(line)))
    meta=re.findall(r'(?m)^\[bb-meta-usage\][^\r\n]*',raw)
    def val(name):
        match=re.search(r'\b'+name+r'=(\d+)',meta[-1]) if meta else None
        return int(match.group(1)) if match else ''
    return dict(reports=len(logs),evictions=counter('evictions'),evicted=counter('evicted'),
        unchains=counter('unchains'),retries=counter('retries'),xip_miss=counter('xip-miss'),
        native_miss=counter('native-miss'),meta_used=val('used'),meta_failures=val('failures'))

def summary():
    if not CSV.exists(): print('No results yet:',CSV);return
    rows=list(csv.DictReader(CSV.open(newline='',encoding='utf-8')))
    for name in PROFILES:
        selected=[r for r in rows if r['profile']==name]
        if not selected:continue
        vals=sorted(float(r['score']) for r in selected if r['render_ok']=='yes' and r['score'])
        median=vals[len(vals)//2] if len(vals)%2 else (vals[len(vals)//2-1]+vals[len(vals)//2])/2 if vals else None
        print(f'{name:8} runs={len(selected)} valid={len(vals)} scores={vals} median={median} '
              f'evictions={[r["evictions"] for r in selected]} unchains={[r["unchains"] for r in selected]}')

def run(a):
    if MARK not in source():raise ValueError('Run apply first')
    names=[x.strip() for x in a.profiles.split(',')]
    if any(n not in PROFILES for n in names):raise ValueError('Unknown profiles; use '+','.join(PROFILES))
    env=os.environ.copy()
    env.update(BB_BBUF='1',BB_CODE_KB='232',BB_CPU='286',BB_SD_BOOT='1',BB_PAGED='1',
        BB_LCD_PERI_HZ='150000000',BB_LCD_SPI_HZ='75000000',BB_LCD_LACE='1',BB_HOT_THRESHOLD='32')
    CSV.parent.mkdir(parents=True,exist_ok=True)
    for name in names:
        chunk,room=PROFILES[name]
        print(f'\n=== {name}: threshold 32, chunk {chunk}, room {room} ===')
        input('Press Enter to build/flash; Ctrl+C to stop...')
        before={str(p) for p in CSV.parent.glob('bb-live-*-console.txt')}
        e=env.copy();e.update(BB_EVICT_CHUNK=str(chunk),BB_EVICT_ROOM=str(room))
        cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts'/'bb_live_run.ps1'),
            '-MicroDOS',a.microdos,'-Blitz86',a.blitz86,'-Port',a.port,'-Seconds',str(a.seconds)]
        result=subprocess.run(cmd,cwd=str(ROOT),env=e)
        logs=[p for p in CSV.parent.glob('bb-live-*-console.txt') if str(p) not in before]
        logs.sort(key=lambda p:p.stat().st_mtime,reverse=True)
        if result.returncode or not logs:print('Failed run; no result saved');continue
        log=logs[0]
        render_ok=input('Was 3D geometry rendered correctly throughout? [y/N]: ').strip().lower() in ('y','yes')
        score_in=input('3DBench score (blank if not completed): ').strip()
        try: score=float(score_in) if score_in else ''
        except ValueError:score=''
        row=dict(date=datetime.datetime.now().isoformat(timespec='seconds'),profile=name,chunk=chunk,
            room=room,score=score,render_ok='yes' if render_ok else 'no',log=str(log),**parse_log(log))
        exists=CSV.exists()
        with CSV.open('a',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS)
            if not exists:writer.writeheader()
            writer.writerow(row)
        print('Recorded',row);summary()
    print('Done. Rebuild control or winner configuration for ongoing development.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for n in ('apply','restore','summary'):sub.add_parser(n)
    p=sub.add_parser('run')
    p.add_argument('--profiles',default='control,small,large,room4,control')
    p.add_argument('--microdos',default=r'C:\microDOS');p.add_argument('--blitz86',default=r'C:\blitz86_v2')
    p.add_argument('--port',default='COM5');p.add_argument('--seconds',type=int,default=180)
    a=parser.parse_args()
    try:
        {'apply':lambda:apply(),'restore':lambda:restore(),'summary':lambda:summary(),
         'run':lambda:run(a)}[a.command]()
    except (ValueError,KeyboardInterrupt) as ex:print('Stopped:',ex,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
