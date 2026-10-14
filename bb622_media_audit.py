#!/usr/bin/env python3
"""Read-only SD-card DOS 6.22 / Descent floppy-image audit.
Usage: python bb622_media_audit.py E:\\BLITZBUS
Checks actual filenames, size, DOS622 A: FAT12 BPB as firmware currently validates.
"""
from __future__ import annotations
import argparse,struct
from pathlib import Path
N=1474560

def expected(d,n):
    return ('DOS622.IMG' if n==1 else f'DOS622{n}.IMG') if d=='A' else f'DESCENT{n}.IMG'

def fat12(b):
    checks=[(b[510:512]==b'\x55\xaa','55AA signature'),(b[0] in (0xEB,0xE9),'boot jump'),
      (struct.unpack_from('<H',b,11)[0]==512,'512-byte sectors'),(b[13]==1,'1 sector/cluster'),
      (struct.unpack_from('<H',b,14)[0]==1,'1 reserved sector'),(b[16]==2,'2 FAT copies'),
      (struct.unpack_from('<H',b,17)[0]==224,'224 root entries'),
      (struct.unpack_from('<H',b,19)[0]==2880,'2880 sectors'),
      (struct.unpack_from('<H',b,22)[0]==9,'9 sectors/FAT'),
      (struct.unpack_from('<H',b,24)[0]==18,'18 sectors/track'),
      (struct.unpack_from('<H',b,26)[0]==2,'2 heads')]
    return [name for good,name in checks if not good]

def files_at(path):
    result=[]
    with path.open('rb') as f:
        f.seek(19*512)
        for _ in range(224):
            e=f.read(32)
            if len(e)<32 or e[0]==0:break
            if e[0]==0xE5 or e[11]&0x18:continue
            name=e[:8].decode('cp437','replace').rstrip()
            ext=e[8:11].decode('cp437','replace').rstrip()
            result.append(name+('.'+ext if ext else ''))
    return result

def audit(directory):
    if not directory.is_dir():raise ValueError(f'Not a folder: {directory}')
    fails=0
    for drive, nums in [('A',range(1,10)),('B',range(1,6))]:
        print(f'\n{drive}: images')
        for n in nums:
            name=expected(drive,n);p=directory/name
            if not p.is_file():
                print(f'  {name:18} MISSING — swap to disk {n} will FAIL')
                if n in ([1,2,3] if drive=='A' else [1,2,3,4,5]):fails+=1
                continue
            size=p.stat().st_size
            if size!=N:
                print(f'  {name:18} INVALID SIZE {size:,} (need {N:,})');fails+=1;continue
            with p.open('rb') as f: boot=f.read(512)
            if drive=='A':
                errors=fat12(boot)
                if errors:
                    print(f'  {name:18} FIRMWARE-REJECTED A: FAT12 validation: {", ".join(errors)}')
                    fails+=1
                    continue
            names=files_at(p)
            print(f'  {name:18} VALID SIZE'+(' + FAT12 BPB' if drive=='A' else '')+f' | root: {", ".join(names[:8]) or "empty"}')
    print('\nOverall: '+('some images missing/invalid' if fails else 'all expected images present'))
    print('This is a read-only check of files accessible to your PC, not a test of the Pico SD driver.')
    return fails

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('folder',type=Path,help='Mounted microSD BLITZBUS folder (for example E:\\BLITZBUS)')
    args=a.parse_args()
    try:audit(args.folder)
    except (ValueError,OSError) as exc:print('ERROR:',exc);raise SystemExit(1)
