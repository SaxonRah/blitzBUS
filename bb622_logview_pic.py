#!/usr/bin/env python3
"""blitzBUS DOS 6.22 sidecar log viewer: never clears terminal or opens COM.

Read-only relative to raw logs. Offline export creates separate derived files.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
import re
import sys
import time

NAME_PATTERN = 'bb-live-*-console.txt'
CELL_RE = re.compile(r'^\[bb622-cells\] row=(\d\d) \|([0-9a-fA-F]{320})\|')
PLAIN_RE = re.compile(r'^\[bb622-screen\] row=(\d\d) (?:\|([^|]*)\||\(cleared\))')
WATCH_RE = re.compile(r'^\[bb622-watch\].*?cs:ip=([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}).*?flags=([0-9A-Fa-f]{4}).*?insns=(\d+) delta=(\d+).*?bios13=(\d+) other=(\d+) ivt=(\d+)')
PIT_RE = re.compile(r'^\[bb-v35-pit\] ([IO]) port=([0-9A-Fa-f]{4}) value=([0-9A-Fa-f]{2})')
EVENT_PREFIX = ('[bb622-picprobe]', '[bb622-watch]', '[bb622-swap]', '[bb622-bmedia]', '[bb622-hostswap]',
                '[bb622-missing-bios]', '[bb622-hddv2]', '[bb622-hdd]', '[bb622-boot]',
                '[bb622-irq0-ab]', '[bb-sd-b]', '[bb-v35-pit]', '[bb-v36-irq]',
                '[bb-v36-irq-summary]', '[bb-v37-irq-profile]', '[bb-v34-clock]',
                '[EMU ALERT]', '[microDOS]', '[bb622-media]')

def latest_log(root: Path) -> Path | None:
    folder = root / 'logs'
    matches = list(folder.glob(NAME_PATTERN))
    return max(matches, key=lambda p: (p.stat().st_mtime_ns, p.name)) if matches else None

def pick_log(args: argparse.Namespace) -> Path | None:
    return args.log if args.log else latest_log(args.root)

def from_cells(s: str) -> str:
    bs = bytes.fromhex(s)
    return ''.join(chr_from_cp437(bs[i]) for i in range(0, 160, 2))

def chr_from_cp437(value: int) -> str:
    # DOS uses 0x00 for unused cells; for text export render as blank.
    return ' ' if value == 0 or value < 32 else bytes((value,)).decode('cp437')

class Screen:
    def __init__(self) -> None:
        self.rows = [' ' * 80 for _ in range(25)]
        self.cell_mode = [False] * 25
        self.last_changed = 0

    def take(self, line: str) -> str | None:
        m = CELL_RE.match(line)
        if m:
            r = int(m.group(1))
            if r > 24:
                return None
            new = from_cells(m.group(2))
            changed = new != self.rows[r]
            self.rows[r] = new
            self.cell_mode[r] = True
            if changed:
                self.last_changed += 1
                return f'SCREEN row={r:02d} |{new.rstrip()}|'
            return None
        m = PLAIN_RE.match(line)
        if m:
            r = int(m.group(1))
            if r > 24 or self.cell_mode[r]:
                return None
            new = (m.group(2) or '').ljust(80)[:80]
            changed = new != self.rows[r]
            self.rows[r] = new
            if changed:
                self.last_changed += 1
                return f'SCREEN row={r:02d} |{new.rstrip()}|'
        return None

    def render(self) -> str:
        return '\n'.join(f'{i:02d} |{r.rstrip():<80}|' for i, r in enumerate(self.rows)) + '\n'

def is_event(line: str) -> bool:
    return line.startswith(EVENT_PREFIX)

def generate_analysis(lines: list[str]) -> str:
    watches = []
    ports: Counter[str] = Counter()
    pit_values: dict[str,set[str]] = {}
    for line in lines:
        m = WATCH_RE.match(line)
        if m:
            watches.append(dict(csip=m.group(1), flags=int(m.group(2),16),
                                insns=int(m.group(3)), delta=int(m.group(4)),
                                bios13=int(m.group(5)), other=int(m.group(6)), ivt=int(m.group(7))))
        pm = PIT_RE.match(line)
        if pm:
            key = pm.group(1) + ':' + pm.group(2).upper()
            ports[key] += 1
            pit_values.setdefault(key, set()).add(pm.group(3).upper())
    r = ["blitzBUS DOS 6.22 — read-only log analysis", "=" * 50,
         f'Total log lines: {len(lines)}', f'CPU samples: {len(watches)}']
    if watches:
        last = watches[-1]
        r.append(f'Last guest CS:IP: {last["csip"]} flags={last["flags"]:04X} IF={int(bool(last["flags"] & 0x200))}')
        r.append(f'Last retired instructions: {last["insns"]:,}')
        r.append(f'Last BIOS/disk cumulative: bios13={last["bios13"]:,} other={last["other"]:,} ivt={last["ivt"]:,}')
        sample = watches[-min(len(watches), 10):]
        places = Counter(w['csip'].split(':')[0] for w in sample)
        r.append(f'Last {len(sample)} samples by code segment: {dict(places)}')
        if len(sample)>=3:
            deltas = [x['delta'] for x in sample]
            stagnant = all(x['bios13']==sample[0]['bios13'] and x['other']==sample[0]['other'] for x in sample)
            r.append(f'Last {len(sample)} instruction deltas: ' + ', '.join(f'{x:,}' for x in deltas))
            r.append('Disk/BIOS call counts unchanged across samples: ' + ('YES' if stagnant else 'NO'))
            r.append('IF clear in every recent sample: ' + ('YES' if all((x['flags']&0x200)==0 for x in sample) else 'NO'))
            if stagnant and len(places)==1 and min(deltas)>100_000:
                r.append('OBSERVATION: guest is executing repeatedly in one segment without recorded BIOS activity.')
                r.append('INTERPRETATION: likely user-code polling loop, not an emulator CPU stop.')
    if ports:
        r.extend(['', 'Sampled port traces (logging may be capped):'])
        for k,n in sorted(ports.items()):
            r.append(f'  {k}: {n} samples, values={",".join(sorted(pit_values.get(k, [])))}')
    count = {tag:sum(1 for l in lines if l.startswith(tag)) for tag in ('[bb622-picprobe]','[bb622-swap]','[bb622-bmedia]','[bb-v36-irq]','[bb622-missing-bios]')}
    r.append('Event counts: ' + ', '.join(f'{k}={v}' for k,v in count.items()))
    r.append('NOTE: guest instruction progress does not imply program progress. PIC/PIT reads are evidence, not a proven cause.')
    return '\n'.join(r)+'\n'

def parse_all(lines: list[str]) -> tuple[Screen,list[str]]:
    screen = Screen()
    events = []
    for line in lines:
        screen.take(line)
        if is_event(line): events.append(line)
    return screen, events

def export_log(path: Path, output: Path | None) -> list[Path]:
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    screen, events = parse_all(lines)
    dest = output or path.parent
    dest.mkdir(parents=True, exist_ok=True)
    base = path.name.removesuffix('.txt')
    files = [dest / f'{base}-screen.txt',dest / f'{base}-events.txt',dest / f'{base}-analysis.txt']
    files[0].write_text(screen.render(),encoding='utf-8')
    files[1].write_text('\n'.join(events)+'\n',encoding='utf-8')
    files[2].write_text(generate_analysis(lines),encoding='utf-8')
    return files

def display_history(path: Path, mode: str, tail: int) -> int:
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    sc = Screen()
    filtered = []
    for line in lines:
        shown = sc.take(line)
        if mode == 'screen' and shown: filtered.append(shown)
        if mode == 'events' and is_event(line): filtered.append(line)
        if mode == 'raw': filtered.append(line)
    for line in filtered[-tail:]: print(line,flush=True)
    return path.stat().st_size

def follow(root: Path, selected: Path | None, mode: str, tail: int, interval: float) -> None:
    path = None
    offset = 0
    pending = b''
    print('blitzBUS sidecar log: independent window; never clears screen or opens COM5.',flush=True)
    print('Press Ctrl+C to stop this viewer; the guest continues running.',flush=True)
    while True:
        found = selected or latest_log(root)
        if found is not None and found.exists():
            if found != path:
                path, pending = found,b''
                print(f'\n=== LOG {path} ===',flush=True)
                offset = display_history(path, mode, tail)
            size = path.stat().st_size
            if size < offset:
                print('--- logfile truncated/restarted ---',flush=True)
                offset,pending = 0,b''
            if size > offset:
                with path.open('rb') as f:
                    f.seek(offset)
                    data=f.read()
                    offset=f.tell()
                content=pending+data
                chunks=content.split(b'\n')
                pending=chunks.pop()
                for raw in chunks:
                    line=raw.rstrip(b'\r').decode('utf-8',errors='replace')
                    if mode=='events' and is_event(line): print(line,flush=True)
                    elif mode=='raw': print(line,flush=True)
                    elif mode=='screen':
                        # Live row updates from both cell and plain screen sources.
                        # A new Screen() is not persistent across polls; display only
                        # actual decoded row records. The exporter builds final state.
                        m=CELL_RE.match(line)
                        if m: print(f'SCREEN row={m.group(1)} |{from_cells(m.group(2)).rstrip()}|',flush=True)
                        else:
                            m=PLAIN_RE.match(line)
                            if m: print(f'SCREEN row={m.group(1)} |{m.group(2) or ""}|',flush=True)
        time.sleep(interval)

def selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        logs=root/'logs';logs.mkdir()
        filename=logs/'bb-live-20261014-174310-console.txt'
        chars=bytearray(160)
        for i,ch in enumerate('A┌─┐Z'):
            val=ch.encode('cp437')[0]
            chars[i*2]=val;chars[i*2+1]=0x1E
        cells=('[bb622-cells] row=04 |'+chars.hex().upper()+'|')
        watch='[bb622-watch] #21 cs:ip=0FF2:87A2 phys=186C2 bytes=B000E643 ss:sp=2131:0BDE ax=000A cx=F5A3 dx=0000 flags=0093 insns=106671259 delta=13630462 native=106671259 slices=34699 bios13=451 other=180631 ivt=180364'
        watch2=watch.replace('#21','#22').replace('106671259','120298639').replace('13630462','13627380')
        watch3=watch.replace('#21','#23').replace('106671259','133904181')
        data='\n'.join([cells,'[bb622-swap] B:2 OK; BIOS media changed',watch,watch2,watch3,'[bb-v35-pit] I port=0040 value=68 cs:ip=0FF2:87A9 tier=native'])+'\n'
        filename.write_text(data,encoding='utf-8')
        sc,evt=parse_all(data.splitlines())
        assert sc.rows[4].startswith('A┌─┐Z') and len(sc.rows[4])==80
        assert '[bb622-swap] B:2' in evt[0] and len(evt)==5
        analysis=generate_analysis(data.splitlines())
        assert 'IF clear in every recent sample: YES' in analysis
        assert 'Disk/BIOS call counts unchanged across samples: YES' in analysis
        assert 'I:0040' in analysis
        outputs=export_log(filename,None)
        assert all(f.exists() for f in outputs)
        assert 'A┌─┐Z' in outputs[0].read_text(encoding='utf-8')
        assert 'B:2 OK' in outputs[1].read_text(encoding='utf-8')
        assert '0FF2:87A2' in outputs[2].read_text(encoding='utf-8')
        assert latest_log(root)==filename
    print('SELFTEST PASS: CP437/cells, immutable raw log, separate screen/events/analysis, IF and PIC/PIT parsing')

def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path.cwd(),help='blitzBUS repository root containing logs/')
    ap.add_argument('--log',type=Path,default=None,help='specific raw console log; otherwise newest')
    ap.add_argument('--follow',action='store_true',help='independent endless live viewer; no COM access')
    ap.add_argument('--mode',choices=['events','screen','raw'],default='events',help='live view without clear screen')
    ap.add_argument('--tail',type=int,default=20,help='recent rows when attaching')
    ap.add_argument('--export',action='store_true',help='write screen/events/analysis text next to source log')
    ap.add_argument('--output',type=Path,default=None,help='optional output directory for exports')
    ap.add_argument('--selftest',action='store_true')
    args=ap.parse_args()
    if args.selftest: selftest();return 0
    path=pick_log(args)
    if args.export:
        if path is None or not path.is_file():
            print(f'No {NAME_PATTERN} files under {args.root / "logs"}',file=sys.stderr);return 2
        for out in export_log(path,args.output): print(f'CREATED: {out}')
    if args.follow:
        try: follow(args.root,args.log,args.mode,max(0,args.tail),0.35)
        except KeyboardInterrupt: print('\nViewer stopped; COM5 and DOS guest unaffected.')
    elif not args.export:
        if not path or not path.is_file(): print(f'No log found under {args.root / "logs"}',file=sys.stderr);return 2
        display_history(path,args.mode,max(0,args.tail))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
