#!/usr/bin/env python3
"""Same-live-run PIC pending-only test for blitzBUS DOS 6.22.

Host-only companion to existing bb622_pic_toggle.ps1, not a firmware patch.
CLI: selftest | audit | trial
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import pathlib
import re
import subprocess
import sys
import time

ACK_RE = re.compile(r'\[bb622-picprobe\] Ctrl\+Y (ON|OFF) pending-only[^\r\n]*')
IN20_RE = re.compile(r'\[bb622-picprobe\] IN20[^\r\n]*')
WATCH_RE = re.compile(r'\[bb622-watch\] #[^\r\n]*')
SENT_RE = re.compile(r'\[bb622-piccontrol\] SENT Ctrl\+Y[^\r\n]*')
DISK_RE = re.compile(r'\[(?:bb622-bmedia|bb-sd-b|bb622-swap|bb622-hddv2)\][^\r\n]*')
F = re.compile(r'([A-Za-z_][A-Za-z_0-9-]*)=([0-9A-Za-z:+.-]+)')


def readlog(path: pathlib.Path) -> str:
    # Opening a raw console log is safe while its PowerShell host is appending.
    return path.read_bytes().decode('utf-8', errors='replace')


def latest(root: pathlib.Path) -> pathlib.Path:
    logs = tuple((root / 'logs').glob('bb-live-*-console.txt'))
    if not logs:
        raise ValueError('No raw DOS console log found under '+str(root / 'logs'))
    return max(logs, key=lambda p: (p.stat().st_mtime_ns, p.name))


def current_session(root: pathlib.Path, path: pathlib.Path, max_age: float = 18.0) -> None:
    selected = latest(root)
    if selected.resolve() != path.resolve():
        raise ValueError(f'Another console log became newest: {selected.name} (expected {path.name})')
    age = time.time() - path.stat().st_mtime
    if age > max_age:
        raise ValueError(f'Console log is stale ({age:.0f}s old). Start the PIC-control DOS runner first; no request sent.')


def last_ack(s: str):
    matches = list(ACK_RE.finditer(s))
    return matches[-1] if matches else None


def parse_field(line: str, field: str):
    m = re.search(r'\b'+re.escape(field)+r'=([\w:+.-]+)', line)
    return m.group(1) if m else '?'


def analyze(log: str, offset: int = 0) -> tuple[str, dict]:
    if offset < 0 or offset > len(log):
        raise ValueError('Invalid analysis offset')
    observed = log[offset:]
    acks = ACK_RE.findall(observed)
    ins = IN20_RE.findall(observed)
    watches = WATCH_RE.findall(observed)
    disks = DISK_RE.findall(observed)
    modes = Counter(parse_field(x,'mode') for x in ins)
    vals = Counter(parse_field(x,'val') for x in ins)
    irr = Counter(parse_field(x,'irr') for x in ins)
    scheduled = [parse_field(x,'scheduled') for x in ins]
    delivered = [parse_field(x,'delivered') for x in ins]
    headers = ['PIC same-run trial analysis',
               f'Firmware ACK events in selected interval: {", ".join(acks) if acks else "NONE"}',
               f'PIC port 20h instrumented reads: {len(ins)}',
               f'PIC read modes: {dict(modes)}',
               f'PIC read values: {dict(vals)}',
               f'PIC IRQ0 IRR observed: {dict(irr)}',
               f'PIT scheduled first/last: {scheduled[0] if scheduled else "?"} / {scheduled[-1] if scheduled else "?"}',
               f'Guest IRQ delivered first/last: {delivered[0] if delivered else "?"} / {delivered[-1] if delivered else "?"}',
               f'CPU watch samples in selected interval: {len(watches)}']
    if watches:
        w0, w1 = watches[0], watches[-1]
        headers += [f'First: {w0}',f'Last:  {w1}']
        try:
            for k in ('insns','bios13','other','ivt'):
                a,b = int(parse_field(w0,k)),int(parse_field(w1,k))
                headers.append(f'{k} delta: {b-a:+,d}')
        except ValueError:
            pass
    headers.append(f'Disk/media events in selected interval: {len(disks)}')
    headers += disks[-12:]
    headers.append('')
    headers.append('OBSERVED PIC READS (latest 24):')
    headers += ins[-24:] or ['(none)']
    headers.append('')
    headers.append('CLASSIFICATION:')
    # This classification deliberately does not equate an unchanged screen
    # with a halted CPU, and never treats the ACK initial irr value as proof.
    if not ins:
        headers.append('No instrumented IN20 occurred in this interval. If ACK was ON, check that guest stayed in the loop and that the PIC native I/O hook was rebuilt/flashed.')
    elif irr.get('01',0) or vals.get('01',0):
        headers.append('Pending IRQ0 bit was visible on at least one recorded PIC read. If Descent still waits, study its PIC read mode/branch behavior; pending IRR alone may not suffice.')
    elif modes.get('ISR',0) and not modes.get('IRR',0):
        headers.append('Guest appears to read PIC ISR, not IRR. Pending-only test does not set ISR; do not conclude PIC scheduling is broken.')
    else:
        headers.append('PIC reads captured, but bit 0 not observed set. Inspect scheduled and PIC mask/initialization before enabling guest IRQ delivery.')
    return '\n'.join(headers)+'\n', {'acks':acks,'ins':ins,'watches':watches,'irr':irr,'mode':modes,'vals':vals}


def trial(root: pathlib.Path, observation: int, timeout: int, logpath: pathlib.Path|None):
    root = root.resolve()
    script = root / 'scripts' / 'bb622_pic_toggle.ps1'
    if not script.is_file():
        raise ValueError(f'Missing existing verified toggle requester: {script}')
    path = logpath or latest(root)
    current_session(root,path)
    first = readlog(path)
    if '[bb622-irq0-ab]' not in first:
        raise ValueError('Selected log is not a DOS6 IRQ0 diagnostic session')
    before = last_ack(first)
    mode = before.group(1) if before else 'OFF (not yet acknowledged in this session)'
    print('TARGET LIVE LOG:',path)
    print('Last acknowledged PIC mode IN THIS LOG:',mode,flush=True)
    # If PIC already ON in the same log, observe it; never toggle it OFF by mistake.
    if before and before.group(1) == 'ON':
        ack_at=before.start()
        print('PIC is already ON in this same run; will not toggle it OFF.',flush=True)
    else:
        print('Sending PIC toggle through installed second-window requester...',flush=True)
        cp = subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
                             '-TimeoutSeconds',str(timeout)],capture_output=True,text=True,timeout=timeout+10)
        output=(cp.stdout or '')+(cp.stderr or '')
        print(output.strip(),flush=True)
        if cp.returncode != 0 or not re.search(r'PICO ACK:.*Ctrl\+Y ON pending-only',output):
            raise RuntimeError('Requester did not confirm PICO ACK: ON in this invocation; check command output.')
        current_session(root,path)
        after=readlog(path)
        ack=last_ack(after)
        if ack is None or ack.group(1) != 'ON':
            raise RuntimeError('Requester ACK could not be proven in the selected SAME log; refusing cross-session interpretation.')
        ack_at=ack.start()
    print(f'Observing {observation}s in the SAME session. Leave Descent running...',flush=True)
    time.sleep(observation)
    # A recent current log is enough; don't require the guest screen to change.
    current_session(root,path,max_age=max(18.0,observation+6.0))
    final=readlog(path)
    report,measurements=analyze(final,ack_at)
    report=f'TARGET LOG: {path}\n' + report
    dest = root/'logs'/('bb622-pictrial-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-report.txt')
    dest.write_text(report,encoding='utf-8')
    print('\n'+report)
    print('SAVED COPYABLE REPORT:',dest)
    if not measurements['ins']:
        print('WARNING: No PIC IN20 trace was observed after ACK ON. Please send raw log and trial report.')


def selftest():
    sample='\n'.join([
     '[bb622-irq0-ab] IRQ0 delivery SUPPRESSED',
     '[bb622-watch] #19 cs:ip=0FF2:87A2 insns=100 bios13=451 other=200 ivt=199',
     '[bb622-picprobe] Ctrl+Y ON pending-only (guest IRQ0 delivery still OFF) irr=00 imr=00 isr=00',
     '[bb622-picprobe] IN20 #1 val=00 mode=IRR irr=00 imr=00 isr=00 scheduled=0 delivered=0',
     '[bb622-picprobe] IN20 #2 val=01 mode=IRR irr=01 imr=00 isr=00 scheduled=4 delivered=0',
     '[bb622-watch] #20 cs:ip=0FF2:87A6 insns=200 bios13=451 other=200 ivt=199',
     '[bb622-picprobe] Ctrl+Y OFF pending-only (guest IRQ0 delivery still OFF) irr=00 imr=00 isr=00',
     '[bb622-picprobe] Ctrl+Y ON pending-only (guest IRQ0 delivery still OFF) irr=00 imr=00 isr=00',
    ])+'\n'
    assert last_ack(sample).group(1)=='ON'
    x,v=analyze(sample,sample.index('Ctrl+Y ON')-len('[bb622-picprobe] '))
    assert len(v['ins'])==2 and v['irr']['01']==1
    assert 'bios13 delta: +0' in x
    assert 'visible on at least one' in x
    blank,z=analyze(sample[:sample.index('[bb622-picprobe] Ctrl+Y ON')])
    assert len(z['ins'])==0 and 'No instrumented IN20' in blank
    isr='[bb622-picprobe] IN20 #1 val=01 mode=ISR irr=01 imr=00 isr=01 scheduled=5 delivered=1\n'
    y,_=analyze(isr)
    assert 'Guest appears to read PIC ISR' in y or 'Pending IRQ0 bit was visible' in y
    with __import__('tempfile').TemporaryDirectory() as temp:
        root=pathlib.Path(temp)
        (root/'logs').mkdir()
        a=root/'logs'/'bb-live-20261014-184232-console.txt'
        a.write_text(sample,encoding='utf-8')
        assert latest(root).resolve()==a.resolve()
        assert last_ack(readlog(a)).group(1)=='ON'
        assert 'IN20' in readlog(a)
    print('SELFTEST PASS: same-log ACK, ON/OFF precedence, IRR classification, watch deltas, missing trace, latest selection')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('selftest','trial','audit'))
    p.add_argument('--root',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parent)
    p.add_argument('--log',type=pathlib.Path)
    p.add_argument('--seconds',type=int,default=12)
    p.add_argument('--timeout',type=int,default=15)
    args=p.parse_args()
    if args.seconds<5 or args.seconds>120: p.error('--seconds must be 5..120')
    if args.timeout<2 or args.timeout>60: p.error('--timeout must be 2..60')
    try:
        if args.command=='selftest':selftest()
        elif args.command=='audit':
            path=args.log or latest(args.root)
            s=readlog(path)
            ack=last_ack(s)
            report,_=analyze(s,ack.start() if ack else 0)
            print('TARGET LOG:',path)
            print('LAST ACK IN THIS SESSION:',ack.group(0) if ack else 'NONE')
            print(report)
        else:trial(args.root,args.seconds,args.timeout,args.log)
    except (Exception,KeyboardInterrupt) as ex:
        print('ERROR:',ex,file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
