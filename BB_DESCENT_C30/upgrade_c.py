#!/usr/bin/env python3
"""Non-destructive FAT16 16 MiB -> 30 MiB image migration; updates blitzBUS private C geometry.

Run offline with Pico powered off. Stdlib only. Never overwrites original automatically.
"""
import argparse, pathlib, struct, shutil, sys, os
SECTOR=512
NEW_SECTORS=61440
NEW_FAT_SECTORS=64

def u16(b,p):return struct.unpack_from('<H',b,p)[0]
def w16(b,p,v):struct.pack_into('<H',b,p,v)

def migrate(src,dst):
    if src.resolve()==dst.resolve():raise ValueError('output must differ from source')
    if dst.exists():raise ValueError('output exists; refusing to overwrite: '+str(dst))
    a=bytearray(src.read_bytes()); b=a[:512]
    if len(a)!=16777216 or b[510:512]!=b'\x55\xaa':raise ValueError('expected 16 MiB existing FAT16 image')
    if (u16(b,11),b[13],u16(b,14),b[16],u16(b,17),u16(b,19),u16(b,22))!=(512,4,1,2,512,32768,32):raise ValueError('unexpected FAT16 BPB: migration aborted without changes')
    old_start=1+2*32+32; new_start=1+2*NEW_FAT_SECTORS+32
    old_clusters=(32768-old_start)//4
    new_clusters=(NEW_SECTORS-new_start)//4
    if (new_clusters+2)*2>NEW_FAT_SECTORS*512:raise AssertionError('new FAT too small')
    fat=a[512:512+32*512]
    if fat[:4]!=b'\xf8\xff\xff\xff':raise ValueError('unexpected FAT signature')
    # Validate all linked references fit old FAT before moving contents.
    for c in range(2,old_clusters+2):
        x=u16(fat,c*2)
        if x not in (0,0xfff7) and x<0xfff8 and x>=old_clusters+2:raise ValueError(f'invalid FAT link at cluster {c}: {x}')
    out=bytearray(NEW_SECTORS*SECTOR)
    out[:512]=a[:512]
    w16(out,19,NEW_SECTORS);w16(out,22,NEW_FAT_SECTORS)
    out[32:36]=b'\0'*4 # 16-bit sector count is authoritative
    for i in range(2):
        off=(1+i*NEW_FAT_SECTORS)*512
        out[off:off+len(fat)]=fat
    old_root=(1+2*32)*512; new_root=(1+2*NEW_FAT_SECTORS)*512
    out[new_root:new_root+32*512]=a[old_root:old_root+32*512]
    for c in range(2,old_clusters+2):
        if u16(fat,c*2)!=0:
            pos_old=(old_start+(c-2)*4)*512;pos_new=(new_start+(c-2)*4)*512
            out[pos_new:pos_new+2048]=a[pos_old:pos_old+2048]
    dst.parent.mkdir(parents=True,exist_ok=True)
    with dst.open('xb') as f:f.write(out);f.flush();os.fsync(f.fileno())
    print(f'Migrated {src} -> {dst}: {len(out):,} bytes; {new_clusters} FAT16 clusters')

def patch_firmware(root):
    sd=root/'sd_boot';drv=sd/'bb_msdos2_boot.c';boot=sd/'bb_sd_boot.c'
    if not drv.is_file() or not boot.is_file():raise ValueError('Stage2C/2D source files missing')
    d=drv.read_text();s=boot.read_text()
    # Handle both older Stage2B and newer Stage2C/2D function bodies, but fail closed.
    replacements=[('0x0340u + 8u, 32768u','0x0340u + 8u, 61440u'),
                  ('0x0340u + 11u, 32u','0x0340u + 11u, 64u'),
                  ('unit == 2u ? 32768u : boot->disk.sector_count','unit == 2u ? 61440u : boot->disk.sector_count')]
    for old,new in replacements:
        if d.count(old)!=1:raise ValueError('DOS driver anchor missing/ambiguous: '+old)
        d=d.replace(old,new)
    # Generic C: LBA bound is 32768u, may occur in both read and write.
    n=s.count('sector >= 32768u')
    if n not in (1,2,3):raise ValueError(f'SD backend C sector count anchor unexpected ({n}); no files changed')
    s=s.replace('sector >= 32768u','sector >= 61440u')
    if s.count('16777216u') < 1:raise ValueError('C image size validation anchor absent')
    s=s.replace('16777216u','31457280u')
    s=s.replace('expected=16777216','expected=31457280')
    s=s.replace('READ-WRITE 16 MiB','READ-WRITE 30 MiB').replace('READ-ONLY 16 MiB','READ-ONLY 30 MiB')
    backup=sd/'c30_backup';backup.mkdir(exist_ok=True)
    for f in (drv,boot):
        target=backup/f.name
        if not target.exists():shutil.copy2(f,target)
    drv.write_text(d);boot.write_text(s)
    print('Private DOS C: BPB and C sector bounds updated to 30 MiB; backups:',backup)

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='cmd',required=True)
    m=sub.add_parser('migrate');m.add_argument('--source',required=True,type=pathlib.Path);m.add_argument('--output',required=True,type=pathlib.Path)
    f=sub.add_parser('firmware');f.add_argument('--root',default=r'C:\blitzBUS',type=pathlib.Path)
    a=p.parse_args()
    if a.cmd=='migrate':migrate(a.source,a.output)
    else:patch_firmware(a.root)
if __name__=='__main__':
    try:main()
    except (OSError,ValueError) as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
