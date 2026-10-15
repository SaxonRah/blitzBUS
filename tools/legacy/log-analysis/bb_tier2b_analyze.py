#!/usr/bin/env python3
"""Tier 2B: compare equal-duration JIT/IRQ samples in LCD on/off console logs."""
import argparse
import re
import statistics
from pathlib import Path

def fields(line):
    return {k:int(v) for k,v in re.findall(r"([\w-]+)=(\d+)",line)}

def analyze(path):
    text=Path(path).read_text(encoding="utf-8",errors="replace").splitlines()
    phase="ON"
    samples=[]
    changes=[]
    pending={}
    for n,line in enumerate(text,1):
        if "[bb-v38] LCD presenter" in line:
            phase="OFF" if "PAUSED" in line else "ON"
            changes.append((n,phase))
        if "[bb-v24] PROFILE" in line:
            d=fields(line)
            if {"wall-ms","jit-insns","jit-calls"}.issubset(d):
                samples.append(dict(line=n,phase=phase,**d))
        if "[bb-v36-irq-summary]" in line and samples:
            d=fields(line)
            samples[-1].update({("irq_"+k):v for k,v in d.items()})
    print("Log:",path," samples:",len(samples)," presenter transitions:",changes)
    intervals=[]
    for a,b in zip(samples,samples[1:]):
        dt=b["wall-ms"]-a["wall-ms"]
        if dt<=0:continue
        # Reports bracketing a toggle are mixed workloads; exclude.
        crossed=any(a["line"]<ln<=b["line"] for ln,_ in changes)
        if crossed:continue
        di=b["jit-insns"]-a["jit-insns"]
        dj=b["jit-calls"]-a["jit-calls"]
        row=dict(phase=b["phase"],start=a["wall-ms"],end=b["wall-ms"],sec=dt/1000,
                 mips=di/dt/1000,calls_per_s=dj*1000/dt,
                 lcd_pct=(b.get("lcd-tick-ms",0)-a.get("lcd-tick-ms",0))/dt*100)
        if "irq_delivered" in a and "irq_delivered" in b:
            row["irq_s"]=(b["irq_delivered"]-a["irq_delivered"])*1000/dt
            row["coalesced_s"]=(b.get("irq_coalesced",0)-a.get("irq_coalesced",0))*1000/dt
        intervals.append(row)
    print(f'{"MODE":<6} {"WINDOW(s)":>10} {"Mguest/s":>11} {"JITcalls/s":>11} {"IRQ/s":>9} {"Coal/s":>9} {"LCDtick%":>9}  TIME')
    for r in intervals:
        print(f'{r["phase"]:<6} {r["sec"]:>10.2f} {r["mips"]:>11.2f} {r["calls_per_s"]:>11.1f} {r.get("irq_s",0):>9.1f} {r.get("coalesced_s",0):>9.1f} {r["lcd_pct"]:>9.2f}  {r["start"]}-{r["end"]} ms')
    usable=[r for r in intervals if r["sec"]>=3]
    for mode in ("ON","OFF"):
        rr=[r for r in usable if r["phase"]==mode and 970<=r.get("irq_s",0)<=1030]
        if rr:
            print(f"{mode} clean intervals={len(rr)} median JIT Mguest/s={statistics.median(r['mips'] for r in rr):.2f} (IRQ 970-1030/s, >=3s)")
        else:print(f"{mode}: no clean windows (need >=3s with IRQ 970-1030/s)")
    a=[r["mips"] for r in usable if r["phase"]=="ON" and 970<=r.get("irq_s",0)<=1030]
    b=[r["mips"] for r in usable if r["phase"]=="OFF" and 970<=r.get("irq_s",0)<=1030]
    if a and b:
        ratio=statistics.median(b)/statistics.median(a)
        print(f"OFF/ON median guest throughput: {ratio:.3f}x ({(ratio-1)*100:+.1f}%).")
        print("WARNING: different benchmark phases can change instruction throughput; repeat ON/OFF/ON with same benchmark and >=3 valid windows each.")
    else:
        print("Not enough clean comparable measurements. Do not infer a performance change.")
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("logs",nargs="+",type=Path)
    args=p.parse_args()
    for path in args.logs:
        analyze(path)
        print()
if __name__=="__main__":main()
