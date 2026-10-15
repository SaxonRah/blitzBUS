#!/usr/bin/env python3
"""Parse blitzBUS Tier 2A Ctrl+P LCD-on/off runs. Python 3, stdlib only."""
import argparse, re
from pathlib import Path

def fields(line):
    return {k: int(v) for k, v in re.findall(r'([a-zA-Z][a-zA-Z0-9_-]*)=(\d+)', line)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('log', type=Path, help='bb-live-...-console.txt')
    a=p.parse_args()
    lines=a.log.read_text(encoding='utf-8',errors='replace').splitlines()
    phase='unknown'
    samples=[]; latest={}
    for n,line in enumerate(lines,1):
        if '[bb-v38] LCD presenter PAUSED' in line:
            phase='paused';latest={};continue
        if '[bb-v38] LCD presenter running' in line:
            phase='running';latest={};continue
        if '[bb-v24] PROFILE' in line: latest['cpu']=fields(line)
        elif '[bb-v36-irq-summary]' in line: latest['irq']=fields(line)
        elif '[bb-jit]' in line: latest['jit']=fields(line)
        elif '[bb-v28-lcd]' in line: latest['lcd']=fields(line)
        elif '[bb-v34-clock]' in line:
            if 'cpu' in latest and 'irq' in latest:
                samples.append(dict(phase=phase,line=n,**latest))
            latest={}
    print(f'Parsed {len(samples)} counter snapshots from {a.log}')
    if not samples:
        print('No matching snapshots. Send the console log with Ctrl+] captures.')
        return 2
    print('Counter snapshots (cumulative since boot for v24/IRQ):')
    for s in samples:
        cpu=s['cpu'];irq=s['irq']
        print(f"line={s['line']:5} phase={s['phase']:7} wall={cpu.get('wall-ms','?')}ms jit_insns={cpu.get('jit-insns','?')} "
              f"irq_delivered={irq.get('delivered','?')} coalesced={irq.get('coalesced','?')} "
              f"lcd_tick_ms={cpu.get('lcd-tick-ms','?')}")
    print('\nSuccessive snapshot deltas (same phase only):')
    any_delta=False
    for x,y in zip(samples,samples[1:]):
        if x['phase']!=y['phase']: continue
        ac,bc=x['cpu'],y['cpu'];ai,bi=x['irq'],y['irq']
        dt=bc.get('wall-ms',0)-ac.get('wall-ms',0)
        if dt<=0:continue
        def d(c,z,key):return c.get(key,0)-z.get(key,0)
        ins=d(bc,ac,'jit-insns'); delivered=d(bi,ai,'delivered')
        edges=d(bi,ai,'edges');coalesced=d(bi,ai,'coalesced')
        lms=d(bc,ac,'lcd-tick-ms')
        any_delta=True
        print(f"  {x['phase']:7} {dt/1000:6.2f}s | jit {ins*1000/dt/1e6:7.2f} Mins/s "
              f"| IRQ {delivered*1000/dt:7.1f}/s | coalesced {coalesced:5d}/{edges:5d} "
              f"| lcd_tick {lms/dt*100:5.2f}% wall")
    if not any_delta:
        print('  Need at least TWO Ctrl+] captures within each running/paused phase.')
    print('\nUse same-phase JIT Mins/s as the primary comparison. LCD DMA/convert figures')
    print('are reported separately from core 1; totals may overlap wall time.')
    print('The older [bb-t1i] counters may be stale; they are not used here.')
    return 0
if __name__=='__main__':raise SystemExit(main())
