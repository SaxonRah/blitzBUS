#!/usr/bin/env python3
import argparse,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('log');a=p.parse_args()
s=Path(a.log).read_text(encoding='utf-8',errors='replace')
for x,y in re.findall(r'T2D CPU CHUNKS=([0-9A-Fa-f]{4})\s+TICKS=([0-9A-Fa-f]{4})',s):
    chunks=int(x,16);ticks=int(y,16)
    if not ticks:print('Timer resolution insufficient');continue
    hz=1193182/65536
    print(f'CPU chunks={chunks}, iterations={chunks*32768:,}, BIOS ticks={ticks}, elapsed~{ticks/hz:.3f}s, iterations/sec~{chunks*32768*hz/ticks:,.0f}')
