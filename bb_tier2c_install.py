#!/usr/bin/env python3
"""Install Tier2C COMs into existing 360K FAT12 image without wiping files."""
import argparse, pathlib, struct, shutil, sys

def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def fatget(f,n):
    j=n*3//2
    v=f[j]|f[j+1]<<8
    return (v>>4)&0xfff if n&1 else v&0xfff
def fatset(f,n,v):
    j=n*3//2
    if n&1:
        f[j]=(f[j]&15)|((v&15)<<4);f[j+1]=(v>>4)&255
    else:
        f[j]=v&255;f[j+1]=(f[j+1]&240)|((v>>8)&15)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--image',default=r'C:\microDOS\build-pico\pico_disk.img')
 p.add_argument('--directory',default=r'C:\blitzBUS\dos_bench\tier2c')
 a=p.parse_args(); image=pathlib.Path(a.image); base=pathlib.Path(a.directory)
 if not image.is_file():raise RuntimeError(f'Image not found: {image}')
 files=[(name,(base/name).read_bytes()) for name in ('T2CCPU.COM','T2CVGA.COM')]
 data=bytearray(image.read_bytes())
 if len(data)!=368640:raise RuntimeError(f'Expected 360K floppy (368640 bytes), got {len(data)}; no changes')
 bps=u16(data,11);spc=data[13];reserved=u16(data,14);nf=data[16];root_n=u16(data,17);total=u16(data,19) or struct.unpack_from('<I',data,32)[0];spf=u16(data,22)
 if bps!=512 or spc==0 or nf<1 or spf==0 or reserved==0 or not root_n or total!=720:raise RuntimeError('Unexpected FAT12 boot parameters, aborting')
 fat_o=reserved*bps; fat_len=spf*bps; root_o=(reserved+nf*spf)*bps;root_size=((root_n*32+bps-1)//bps)*bps;data_o=root_o+root_size
 cluster_bytes=spc*bps; clusters=(len(data)-data_o)//cluster_bytes
 if clusters>4084:raise RuntimeError('Not FAT12')
 fat=bytearray(data[fat_o:fat_o+fat_len]); entries={}
 for i in range(root_n):
    off=root_o+i*32;e=data[off:off+32];
    if e[0] in (0,229) or e[11]==15:continue
    entries[bytes(e[:11])]=i
 for name,_ in files:
    stem,ext=name.split('.');name83=(stem.ljust(8)+ext.ljust(3)).encode('ascii')
    if name83 in entries:raise RuntimeError(f'{name} already exists; refusing to overwrite your copy')
 needed=sum((len(blob)+cluster_bytes-1)//cluster_bytes for _,blob in files)
 available=[c for c in range(2,clusters+2) if fatget(fat,c)==0]
 slots=[i for i in range(root_n) if data[root_o+i*32] in (0,229)]
 if len(available)<needed or len(slots)<len(files):raise RuntimeError(f'Not enough space: {len(available)} free clusters ({needed} needed), {len(slots)} root slots')
 take=iter(available); slot=iter(slots)
 for name,blob in files:
    count=(len(blob)+cluster_bytes-1)//cluster_bytes
    chain=[next(take) for _ in range(count)]
    for i,c in enumerate(chain):
       fatset(fat,c,chain[i+1] if i+1<count else 0xfff)
       at=data_o+(c-2)*cluster_bytes
       if at+cluster_bytes>len(data):raise RuntimeError('FAT cluster outside image')
       data[at:at+cluster_bytes]=blob[i*cluster_bytes:(i+1)*cluster_bytes].ljust(cluster_bytes,b'\0')
    o=root_o+next(slot)*32
    stem,ext=name.split('.')
    data[o:o+32]=bytes(32)
    data[o:o+11]=(stem.ljust(8)+ext.ljust(3)).encode('ascii')
    data[o+11]=0x20
    struct.pack_into('<H',data,o+26,chain[0]);struct.pack_into('<I',data,o+28,len(blob))
    print(f'Added {name}: {len(blob)} bytes, {count} FAT clusters')
 for k in range(nf):data[fat_o+k*fat_len:fat_o+(k+1)*fat_len]=fat
 bak=image.with_suffix(image.suffix+'.before-tier2c.bak')
 if bak.exists():raise RuntimeError(f'Backup already exists: {bak}; refusing to replace it')
 shutil.copy2(image,bak)
 image.write_bytes(data)
 if len(image.read_bytes())!=368640:raise RuntimeError('Size validation failed')
 print('Image updated:',image,'\nOriginal backup:',bak)
 print('Rebuild blitzbus_pico_b86_dos target, then flash it via bb_live_run.ps1')
if __name__=='__main__':
 try:main()
 except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
