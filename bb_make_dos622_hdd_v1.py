#!/usr/bin/env python3
"""Create an isolated 65x16x63 BIOS HDD image for MS-DOS 6.22 Setup.
No Microsoft system files are shipped. Never modifies an existing file.
Usage: python bb_make_dos622_hdd_v1.py [--output DOS622_HDD.IMG]
"""
import argparse
from pathlib import Path
import struct

CYLS, HEADS, SPT = 65, 16, 63
SECTORS = CYLS * HEADS * SPT
START = 63
PART_SECTORS = SECTORS - START
BPS, SPC, RESERVED, FATS, ROOT_ENTRIES, SPF = 512, 4, 1, 2, 512, 64
MBR_BOOT = bytes.fromhex('fa 31 c0 8e d0 bc 00 7c 8e d8 8e c0 fb be 00 7c bf 00 06 b9 00 01 fc f3 a5 ea 1e 06 00 00 bb 00 7c b4 02 b0 01 b9 01 00 ba 80 01 cd 13 72 05 ea 00 7c 00 00 eb fe')

def sectors_image():
    assert SECTORS == 65520 and PART_SECTORS == 65457
    assert (PART_SECTORS - (RESERVED + FATS*SPF + (ROOT_ENTRIES*32)//BPS))//SPC >= 4085
    mbr = bytearray(512)
    mbr[:len(MBR_BOOT)] = MBR_BOOT
    off=446
    mbr[off:off+16] = bytes([0x80, 0x01, 0x01, 0x00, 0x06, 0x0f, 0x3f, 0x40]) + struct.pack('<II', START, PART_SECTORS)
    mbr[510:512] = b'\x55\xaa'
    bs=bytearray(512)
    bs[0:3]=b'\xeb\x3c\x90'; bs[3:11]=b'BLITZBUS'
    struct.pack_into('<H',bs,11,BPS)
    bs[13]=SPC
    struct.pack_into('<H',bs,14,RESERVED)
    bs[16]=FATS
    struct.pack_into('<H',bs,17,ROOT_ENTRIES)
    struct.pack_into('<H',bs,19,PART_SECTORS)
    bs[21]=0xf8
    struct.pack_into('<H',bs,22,SPF)
    struct.pack_into('<H',bs,24,SPT)
    struct.pack_into('<H',bs,26,HEADS)
    struct.pack_into('<I',bs,28,START)
    struct.pack_into('<I',bs,32,0)
    bs[36]=0x80; bs[38]=0x29
    struct.pack_into('<I',bs,39,0x62219626)
    bs[43:54]=b'DOS622 HDD '
    bs[54:62]=b'FAT16   '
    bs[62:64]=b'\xcd\x18' # unbootable until DOS6 Setup/SYS installs real boot code
    bs[510:512]=b'\x55\xaa'
    fat=bytearray(512)
    fat[:4]=bytes([0xf8,0xff,0xff,0xff])
    return bytes(mbr),bytes(bs),bytes(fat)

def inspect(path):
    if path.stat().st_size!=SECTORS*BPS:raise ValueError('bad size')
    with path.open('rb') as f:
        mbr=f.read(512)
        f.seek(START*BPS); boot=f.read(512)
        f.seek((START+RESERVED)*BPS);fat1=f.read(512)
        f.seek((START+RESERVED+SPF)*BPS);fat2=f.read(512)
    if mbr[510:512]!=b'\x55\xaa' or boot[510:512]!=b'\x55\xaa':raise ValueError('missing signatures')
    if mbr[446:454]!=bytes([0x80,1,1,0,6,15,63,64]):raise ValueError('bad partition CHS/type')
    if struct.unpack_from('<II',mbr,454)!=(START,PART_SECTORS):raise ValueError('bad partition LBA')
    if struct.unpack_from('<H',boot,19)[0]!=PART_SECTORS or struct.unpack_from('<I',boot,28)[0]!=START:raise ValueError('bad BPB')
    if fat1[:4]!=b'\xf8\xff\xff\xff' or fat1!=fat2:raise ValueError('bad FAT copies')
    return {'size_bytes':path.stat().st_size,'cylinders':CYLS,'heads':HEADS,'sectors_per_track':SPT,
        'part_start':START,'part_sectors':PART_SECTORS,'fat16':True,'bootable_after_dos_sys':True}

def make(output):
    mbr,bs,fat=sectors_image()
    with output.open('xb') as f:
        f.truncate(SECTORS*BPS)
        f.seek(0);f.write(mbr)
        f.seek(START*BPS);f.write(bs)
        f.seek((START+RESERVED)*BPS);f.write(fat)
        f.seek((START+RESERVED+SPF)*BPS);f.write(fat)
    print('CREATED', output)
    print('VERIFIED', inspect(output))

def selftest():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        p=Path(td)/'disk.img';make(p)
        assert inspect(p)['part_sectors']==65457
        try:make(p)
        except FileExistsError:pass
        else:raise AssertionError('refused-overwrite test failed')
    print('SELFTEST PASS partition MBR/boot sector/FAT copies/overwrite refusal')

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=Path('DOS622_HDD.IMG'))
    ap.add_argument('--selftest',action='store_true')
    args=ap.parse_args()
    if args.selftest:selftest()
    else:make(args.output)
