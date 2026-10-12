#!/usr/bin/env python3
"""Replace exactly T2CCPU.COM and T2CVGA.COM in existing 360K FAT12 image."""
import argparse, pathlib, struct, shutil, sys

def u16(b,i): return struct.unpack_from('<H',b,i)[0]
def fatget(f,n):
    j=n*3//2; v=f[j]|f[j+1]<<8
    return (v>>4)&0xfff if n&1 else v&0xfff

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--image',default=r'C:\blitzBUS\media\dosbench3d.img')
    p.add_argument('--directory',default=r'C:\blitzBUS\dos_bench\tier2c')
    a=p.parse_args()
    ip=pathlib.Path(a.image); dp=pathlib.Path(a.directory)
    disk=bytearray(ip.read_bytes())
    if len(disk)!=368640:raise ValueError('Not a 360K disk image')
    bps=u16(disk,11);spc=disk[13];reserved=u16(disk,14);nf=disk[16];root_n=u16(disk,17);spf=u16(disk,22)
    if bps!=512 or not (spc and reserved and nf and root_n and spf):raise ValueError('Unexpected FAT12 boot parameters')
    root=(reserved+nf*spf)*bps;data_off=root+((root_n*32+bps-1)//bps)*bps
    fat=bytearray(disk[reserved*bps:reserved*bps+spf*bps]);cluster_bytes=spc*bps
    for fn in ('T2CCPU.COM','T2CVGA.COM'):
        name=(fn.split('.')[0].ljust(8)+'COM').encode('ascii')
        match=[root+i*32 for i in range(root_n) if disk[root+i*32:root+i*32+11]==name]
        if len(match)!=1:raise ValueError(f'{fn}: expected exactly one directory entry, found {len(match)}')
        pos=match[0];first=u16(disk,pos+26);length=struct.unpack_from('<I',disk,pos+28)[0]
        if length<=0 or first<2:raise ValueError(f'{fn}: invalid FAT entry')
        chain=[];visited=set();c=first
        while c<0xff8:
            if c in visited or c<2:raise ValueError(f'{fn}: corrupt FAT chain')
            visited.add(c);chain.append(c);c=fatget(fat,c)
        new=(dp/(fn.replace('.COM','_FIXED.COM'))).read_bytes()
        if len(new)>len(chain)*cluster_bytes:raise ValueError(f'{fn}: replacement needs more allocated clusters; stopping safely')
        for i,c in enumerate(chain):
            dst=data_off+(c-2)*cluster_bytes
            if dst<0 or dst+cluster_bytes>len(disk):raise ValueError('Cluster beyond disk')
            disk[dst:dst+cluster_bytes]=new[i*cluster_bytes:(i+1)*cluster_bytes].ljust(cluster_bytes,b'\0')
        struct.pack_into('<I',disk,pos+28,len(new))
        print(f'Replaced {fn} ({length} -> {len(new)} bytes)')
    backup=ip.with_name(ip.name+'.before-tier2c-repair.bak')
    if backup.exists():raise FileExistsError(f'Repair backup already exists: {backup}')
    shutil.copy2(ip,backup)
    ip.write_bytes(disk)
    print('Updated:',ip,'\nBackup:',backup)
if __name__=='__main__':
    try:main()
    except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
