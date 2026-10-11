#!/usr/bin/env python3
"""Safely replace only T2CCPU.COM inside existing 360KB FAT12 image."""
import argparse
import pathlib
import shutil
import struct
import sys

def get16(buf,off):return struct.unpack_from('<H',buf,off)[0]
def fat12(fat,n):
    i=n*3//2; w=fat[i]|fat[i+1]<<8
    return (w>>4)&0xfff if n&1 else w&0xfff

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--image',default=r'C:\blitzBUS\media\dosbench3d.img')
    ap.add_argument('--com',default=r'C:\blitzBUS\dos_bench\tier2c\T2CCPU.COM')
    a=ap.parse_args()
    path=pathlib.Path(a.image)
    data=bytearray(path.read_bytes());new=pathlib.Path(a.com).read_bytes()
    if len(data)!=368640:raise ValueError('Expected 360KB FAT12 floppy')
    bps=get16(data,11);spc=data[13];res=get16(data,14)
    fats=data[16];nent=get16(data,17);spf=get16(data,22)
    if (bps,spc,res,fats,nent,spf)!=(512,2,1,2,112,2):
        raise ValueError(f'Unexpected FAT12 geometry: {bps,spc,res,fats,nent,spf}')
    root=(res+fats*spf)*bps
    start=root+((nent*32+bps-1)//bps)*bps
    fat=data[res*bps:(res+spf)*bps]
    matches=[root+i*32 for i in range(nent) if data[root+i*32:root+i*32+11]==b'T2CCPU  COM']
    if len(matches)!=1:raise ValueError(f'Expected one T2CCPU.COM entry, found {len(matches)}')
    ent=matches[0];cluster=get16(data,ent+26); chain=[];seen=set()
    while cluster<0xff8:
        if cluster<2 or cluster in seen:raise ValueError('Bad FAT12 chain')
        seen.add(cluster);chain.append(cluster);cluster=fat12(fat,cluster)
    if len(new)>len(chain)*bps*spc:raise ValueError('Replacement exceeds allocated cluster capacity')
    for n,c in enumerate(chain):
        off=start+(c-2)*bps*spc
        if off<start or off+bps*spc>len(data):raise ValueError('Bad cluster address')
        data[off:off+bps*spc]=new[n*bps*spc:(n+1)*bps*spc].ljust(bps*spc,b'\0')
    old=get16(data,ent+28)
    struct.pack_into('<I',data,ent+28,len(new))
    backup=path.with_name(path.name+'.before-cpu-diag.bak')
    if backup.exists():raise FileExistsError(f'Backup exists; refusing overwrite: {backup}')
    shutil.copy2(path,backup)
    path.write_bytes(data)
    print(f'T2CCPU.COM replaced ({old} -> {len(new)} bytes); VGA and 3DBENCH unchanged')
    print('Backup:',backup)
    print('Rebuild embedded md_pico_blobs.S.obj and firmware before flashing.')
if __name__=='__main__':
    try:main()
    except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
