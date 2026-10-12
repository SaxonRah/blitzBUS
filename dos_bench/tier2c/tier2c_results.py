#!/usr/bin/env python3
"""Tier 2C: compute fixed-workload rates from T2CCPU/T2CVGA DOS output."""
import argparse
from pathlib import Path
import re

PIT_HZ=1193182/65536  # BIOS coarse ticks, approximately 18.2065 Hz
PATTERN=re.compile(r'T2C\s+(CPU|VGA)\s+CHUNKS=([0-9A-Fa-f]{4})\s+TICKS=([0-9A-Fa-f]{4})',re.I)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('logs',nargs='+',help='DOS console transcript(s) with T2C result lines')
    args=p.parse_args()
    found=[]
    for filename in args.logs:
        body=Path(filename).read_text(encoding='utf-8',errors='replace')
        for match in PATTERN.finditer(body):
            mode,chunks,ticks=match.groups()
            chunks=int(chunks,16);ticks=int(ticks,16)
            if ticks==0:
                print('WARNING zero ticks, skipping')
                continue
            seconds=ticks/PIT_HZ
            unit_count=chunks*32768
            rate=unit_count/seconds
            found.append((mode.upper(),chunks,ticks,seconds,rate,filename))
    print(f'{"MODE":<5} {"CHUNKS":>7} {"TICKS":>6} {"SECONDS":>10} {"OPS/SEC":>15}  SOURCE')
    for mode,chunks,ticks,seconds,rate,filename in found:
        print(f'{mode:<5} {chunks:>7} {ticks:>6} {seconds:>10.3f} {rate:>15,.0f}  {filename}')
    cpu=[r[4] for r in found if r[0]=='CPU']
    vga=[r[4] for r in found if r[0]=='VGA']
    if cpu and vga:
        print('CPU and VGA rates are separate workloads; do NOT divide them to infer bus latency.')
    if not found:
        print('No T2C results found. Expected: T2C CPU CHUNKS=001A TICKS=0024 (HEX)')
if __name__=='__main__':main()
