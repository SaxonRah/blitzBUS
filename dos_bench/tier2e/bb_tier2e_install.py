#!/usr/bin/env python3
"""Add T2ECPU.COM to an existing 360K FAT12 disk without removing programs."""
import argparse, pathlib, shutil, struct, sys

def u16(b,o): return struct.unpack_from('<H',b,o)[0]
def get12(f,n):
    p=n*3//2
    val=f[p]|(f[p+1]<<8)
    return ((val>>4)&4095) if n&1 else (val&4095)
def set12(f,n,v):
    p=n*3//2
    if n&1:
        f[p]=(f[p]&15)|((v&15)<<4);f[p+1]=(v>>4)&255
    else:
        f[p]=v&255;f[p+1]=(f[p+1]&240)|((v>>8)&15)
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--image',required=True)
    p.add_argument('--com',required=True)
    a=p.parse_args()
    img=pathlib.Path(a.image);src=pathlib.Path(a.com)
    b=bytearray(img.read_bytes()); exe=src.read_bytes()
    if len(b)!=368640:raise ValueError('Expected 360K disk; no write performed')
    bps=u16(b,11);spc=b[13];nf=b[16];reserved=u16(b,14);spf=u16(b,22);root_n=u16(b,17)
    if bps!=512 or spc<1 or nf!=2 or reserved<1 or spf<1 or root_n<16 or u16(b,19)!=720:raise ValueError('Unexpected FAT12 BPB')
    fat_o=reserved*bps; fat_size=spf*bps
    root_o=(reserved+nf*spf)*bps; data_o=root_o+((root_n*32+bps-1)//bps)*bps
    cluster_sz=bps*spc; cluster_max=(len(b)-data_o)//cluster_sz+1
    name=b'T2ECPU  COM'
    slot=None
    for i in range(root_n):
        o=root_o+i*32
        if b[o:o+11]==name:raise ValueError('T2ECPU.COM already on image; no changes')
        if slot is None and b[o] in (0,229):slot=o
    if slot is None:raise ValueError('No FAT12 directory slot')
    f=bytearray(b[fat_o:fat_o+fat_size])
    count=(len(exe)+cluster_sz-1)//cluster_sz
    free=[n for n in range(2,cluster_max+1) if get12(f,n)==0]
    if len(free)<count:raise ValueError('Not enough free FAT clusters')
    chain=free[:count]
    for j,n in enumerate(chain):
        set12(f,n,chain[j+1] if j+1<count else 4095)
        o=data_o+(n-2)*cluster_sz
        if o+cluster_sz>len(b):raise ValueError('Cluster beyond image')
        b[o:o+cluster_sz]=exe[j*cluster_sz:(j+1)*cluster_sz].ljust(cluster_sz,b'\0')
    b[slot:slot+32]=bytes(32)
    b[slot:slot+11]=name;b[slot+11]=0x20
    struct.pack_into('<H',b,slot+26,chain[0]);struct.pack_into('<I',b,slot+28,len(exe))
    for i in range(nf):b[fat_o+i*fat_size:fat_o+(i+1)*fat_size]=f
    backup=img.with_name(img.name+'.before-tier2e.bak')
    if backup.exists():raise ValueError(f'Backup exists: {backup}; no changes')
    shutil.copy2(img,backup)
    img.write_bytes(b)
    print('ADDED T2ECPU.COM',len(exe),'bytes. Backup:',backup)
if __name__=='__main__':
    try:main()
    except Exception as e: print('ERROR:',e,file=sys.stderr);sys.exit(1)
