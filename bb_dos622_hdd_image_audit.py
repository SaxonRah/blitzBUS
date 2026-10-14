#!/usr/bin/env python3
"""READ ONLY FAT16/MBR audit for blitzBUS MS-DOS 6.22 HDD image.
Usage: python bb_dos622_hdd_image_audit.py X:\\BLITZBUS\\DOS622_HDD.IMG
IMPORTANT: work on a backup image; never edits any sectors.
"""
import argparse, os, struct, sys
from pathlib import Path
SECTOR=512
TOTAL=65520

def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def inspect(path):
    with Path(path).open('rb') as f:
        size=os.fstat(f.fileno()).st_size
        if size != TOTAL*SECTOR:raise ValueError(f'Expected {TOTAL*SECTOR} bytes; found {size}')
        def read(lba,n=1):
            if lba<0 or n<1 or lba+n>TOTAL:raise ValueError('Sector outside image')
            f.seek(lba*SECTOR)
            b=f.read(n*SECTOR)
            if len(b)!=n*SECTOR:raise ValueError('Short image read')
            return b
        mbr=read(0);entry=mbr[446:462]
        if mbr[510:512]!=b'\x55\xaa':raise ValueError('MBR signature missing')
        ptype=entry[4];start=u32(entry,8);count=u32(entry,12)
        if entry[0]!=0x80 or ptype!=0x06 or start!=63 or count!=65457:
            raise ValueError(f'Unexpected MBR partition: boot={entry[0]:02X}, type={ptype:02X}, start={start}, sectors={count}')
        boot=read(start)
        if boot[510:512]!=b'\x55\xaa':raise ValueError('Volume boot signature missing')
        bps=u16(boot,11);spc=boot[13];res=u16(boot,14);nf=boot[16];rootents=u16(boot,17)
        tot=u16(boot,19) or u32(boot,32);spf=u16(boot,22);heads=u16(boot,26);spt=u16(boot,24);hidden=u32(boot,28)
        if bps!=512 or spc!=4 or nf!=2 or spf!=64 or res==0 or rootents!=512 or hidden!=start or tot!=count or heads!=16 or spt!=63:
            raise ValueError(f'Unexpected FAT16 BPB: BPS={bps}, SPC={spc}, res={res}, fats={nf}, SPF={spf}, root={rootents}, hidden={hidden}, total={tot}, heads={heads}, SPT={spt}')
        fat1_lba=start+res;fat2_lba=fat1_lba+spf
        fat1=read(fat1_lba,spf);fat2=read(fat2_lba,spf)
        differing=sum(a!=b for a,b in zip(fat1,fat2))
        root_lba=fat2_lba+spf
        root_secs=(rootents*32+511)//512
        cluster0=root_lba+root_secs
        clusters=(tot-(cluster0-start))//spc
        if not (4085<=clusters<65525) or len(fat1)//2<clusters+2:raise ValueError('Invalid FAT16 cluster geometry')
        root=read(root_lba,root_secs)
        root_names=[];first_dos=None
        for i in range(rootents):
            e=root[i*32:(i+1)*32]
            if e[0]==0:break
            if e[0]==0xE5 or e[11] in (0x0F,):continue
            if e[11]&0x08:continue
            name=e[:8].decode('cp437','replace').strip();ext=e[8:11].decode('cp437','replace').strip()
            display=name+(('.'+ext) if ext else '')
            root_names.append(display)
            if name.upper()=='DOS' and e[11]&0x10:first_dos=u16(e,26)
        print(f'Image: {path} ({size} bytes)')
        print(f'MBR: bootable FAT16 type=06 start-LBA={start} sectors={count}')
        print(f'BPB: {heads} heads x {spt} spt, {spc} sectors/cluster, {clusters} clusters, {spf} sectors/FAT')
        print(f'FAT copies: {len(fat1)} bytes each, mismatch bytes={differing}')
        print(f'Root directory entries: {", ".join(root_names[:25]) if root_names else "none"}')
        print(f'DOS directory first cluster: {first_dos if first_dos is not None else "not present"}')
        if fat1[:4] not in (b'\xF8\xFF\xFF\xFF',b'\xF8\xFF\xFF\x0F'):
            print('WARNING: FAT16 reserved cluster headers unexpected:',fat1[:4].hex())
        if differing:
            print('WARNING: FAT tables differ. Preserve image; do not repair automatically.')
            return False
        print('AUDIT PASS: structural MBR/BPB/FAT mirror checks; not a complete DOS filesystem fsck')
        return True

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path)
    a=p.parse_args()
    try:sys.exit(0 if inspect(a.image) else 2)
    except (OSError,ValueError,struct.error) as exc:
        print('AUDIT ERROR:',exc,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
