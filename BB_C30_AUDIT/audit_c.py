#!/usr/bin/env python3
"""Read-only FAT16 audit for blitzBUS DRIVE_C.IMG. Python 3 standard library only."""
import argparse
import collections
import pathlib
import struct
import sys


def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]

def audit(path):
    b = path.read_bytes()
    if len(b) < 512: raise ValueError('Image shorter than one sector')
    if b[510:512] != b'\x55\xaa': print('WARNING: missing 55 AA boot signature')
    bps=u16(b,11); spc=b[13]; res=u16(b,14); nfats=b[16]; rootent=u16(b,17)
    total16=u16(b,19); media=b[21]; fatsec=u16(b,22); spt=u16(b,24); heads=u16(b,26); total32=u32(b,32)
    total=total16 or total32
    if bps!=512 or not spc or spc&(spc-1) or not fatsec or nfats not in (1,2):
        raise ValueError('Unexpected geometry; expected 512-byte FAT16')
    rootsecs=(rootent*32+bps-1)//bps
    data_start=res+nfats*fatsec+rootsecs
    clusters=(total-data_start)//spc
    if clusters < 4085 or clusters >= 65525: print('WARNING: cluster count is outside ordinary FAT16 range')
    print(f'Image: {path} ({len(b):,} bytes)')
    print(f'BPB: bytes/sector={bps}, sectors/cluster={spc}, reserved={res}, FATs={nfats}, FAT sectors={fatsec}, root entries={rootent}')
    print(f'BPB: total16={total16}, total32={total32}, total={total}, sectors/track={spt}, heads={heads}, media=0x{media:02X}')
    print(f'Layout: FAT1 LBA {res}, FAT2 LBA {res+fatsec}, root LBA {res+nfats*fatsec}, data LBA {data_start}')
    print(f'Clusters: {clusters}, bytes/cluster={bps*spc}, expected capacity={total*bps:,} bytes')
    if len(b) != total*bps: print(f'WARNING: image size differs from BPB: {len(b)-total*bps:+,} bytes')
    if (clusters+2)*2 > fatsec*bps: print('ERROR: FAT capacity insufficient for BPB cluster count')
    fatcopies=[b[(res+i*fatsec)*bps:(res+(i+1)*fatsec)*bps] for i in range(nfats)]
    if len(set(fatcopies))>1:
        mismatches=[i for i in range(0, min(map(len,fatcopies)),2) if fatcopies[0][i:i+2]!=fatcopies[1][i:i+2]]
        print(f'WARNING: FAT copies differ at {len(mismatches)} entries; first offsets: {mismatches[:20]}')
    else: print('FAT copies: IDENTICAL')
    fat=fatcopies[0]
    cnt=collections.Counter()
    for cl in range(2,clusters+2):
        v=u16(fat,cl*2)
        if v==0: kind='free'
        elif v==0xFFF7: kind='bad'
        elif 0xFFF0<=v<=0xFFF6: kind='reserved'
        elif v>=0xFFF8: kind='eof'
        elif 2<=v<clusters+2: kind='next'
        else: kind='out_of_range'
        cnt[kind]+=1
    print('FAT counts: '+', '.join(f'{k}={cnt[k]}' for k in ['free','next','eof','bad','reserved','out_of_range']))
    print(f'Free bytes from FAT: {cnt["free"]*spc*bps:,}; DOS2 expected if full FAT scanned')
    print('First 24 cluster entries: '+ ' '.join(f'{i}:0x{u16(fat,i*2):04X}' for i in range(2,min(26,clusters+2))))
    if cnt['out_of_range'] or cnt['reserved']:
        print('WARNING: invalid/reserved entries in data-cluster FAT; do not modify image until investigated')
    if total16 and total16>65535: print('ERROR: total16 overflow')
    if not total16: print('WARNING: DOS 2.00 may not support total32 BPB field')
    if cnt['free']*spc*bps!=12288: print('NOTE: DOS previously reported 12,288 bytes; FAT count differs, pointing to DOS-side FAT accounting or geometry.')
    if nfats==2 and len(set(fatcopies))>1: return 2
    return 0

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image', nargs='?', type=pathlib.Path, default=pathlib.Path('O:/BLITZBUS/DRIVE_C.IMG'))
    args=ap.parse_args()
    try: sys.exit(audit(args.image))
    except (OSError, ValueError, struct.error) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
