#!/usr/bin/env python3
"""Build, populate and thoroughly verify a NEW blitzBUS 30 MiB FAT16 image."""
import argparse
import hashlib
import os
import struct
import sys
from pathlib import Path
from fat16tool import FAT16, FatError, dosname
from check_chains import audit

BYTES = 30*1024*1024

def sha(data):return hashlib.sha256(data).hexdigest()
def fmt(n):return f'{n:,}'

def read_command_from_a(path):
    """Return COMMAND.COM from a 360 KiB FAT12 BOOT.IMG without altering it."""
    raw=path.read_bytes()
    if len(raw)!=368640:raise ValueError('A: BOOT.IMG must be 360 KiB')
    bps=struct.unpack_from('<H',raw,11)[0]
    spc=raw[13];res=struct.unpack_from('<H',raw,14)[0]
    nfats=raw[16];roots=struct.unpack_from('<H',raw,17)[0]
    spfat=struct.unpack_from('<H',raw,22)[0]
    if (bps,spc,res,nfats)!=(512,2,1,2):raise ValueError('Unexpected A: FAT12 geometry')
    root_start=(res+nfats*spfat)*bps
    rootbytes=((roots*32+511)//512)*512
    data_start=root_start+rootbytes
    fat=raw[res*bps:(res+spfat)*bps]
    match=None
    for offset in range(root_start,root_start+roots*32,32):
        ent=raw[offset:offset+32]
        if ent[:11]==b'COMMAND COM':match=ent;break
    if match is None:raise ValueError('COMMAND.COM not found on A:')
    size=struct.unpack_from('<I',match,28)[0];c=struct.unpack_from('<H',match,26)[0]
    parts=[];visited=set()
    while True:
        if not 2<=c<355 or c in visited:raise ValueError('Invalid COMMAND.COM FAT12 chain')
        visited.add(c)
        off=data_start+(c-2)*spc*bps
        parts.append(raw[off:off+spc*bps])
        o=(c*3)//2
        value=(fat[o]|(fat[o+1]<<8))
        nxt=(value>>4 if c&1 else value&0xFFF)
        if nxt>=0xFF8:break
        c=nxt
    contents=b''.join(parts)[:size]
    if size!=15480 or len(contents)!=size:raise ValueError('A: COMMAND.COM does not have expected 15,480 bytes')
    return contents

def main():
    p=argparse.ArgumentParser(description='Build clean persistent blitzBUS C: image; never touches the SD card')
    p.add_argument('--boot-template',required=True,help='Existing 30 MiB C: image (first sector only used)')
    p.add_argument('--descent',required=True,help='Directory with 25 fully extracted Descent files')
    p.add_argument('--disk-com',required=True,help='Current working 175-byte DISK.COM')
    p.add_argument('--boot-a',required=True,help='Minimal 360 KiB BOOT.IMG containing COMMAND.COM')
    p.add_argument('--output',required=True,help='New filename, must not already exist')
    p.add_argument('--hello',help='Optional original Windows HELLO.TXT to put in TOOLS')
    a=p.parse_args()
    out=Path(a.output).resolve()
    if out.exists():raise ValueError('Refusing to overwrite existing image: '+str(out))
    template=Path(a.boot_template).resolve()
    if out==template:raise ValueError('Output cannot equal source')
    files_dir=Path(a.descent).resolve()
    if not files_dir.is_dir():raise ValueError('Descent staging folder not found')
    expected={'DESCENT.HOG':7261423,'DESCENT.PIG':7640220,'DESCENT.UBN':898025,'SETUP.UBN':219405}
    sources={}
    for f in sorted(files_dir.iterdir()):
        if not f.is_file():raise ValueError('Descent staging must contain only ordinary files: '+str(f))
        dosname(f.name)
        if f.name.upper() in sources:raise ValueError('Duplicate DOS filename: '+f.name)
        sources[f.name.upper()]=f
    if len(sources)!=25:raise ValueError(f'Expected 25 extracted Descent files, found {len(sources)}; refusing incomplete install')
    for name,size in expected.items():
        if name not in sources or sources[name].stat().st_size!=size:
            raise ValueError(f'{name}: expected {size:,} bytes from the verified five-disk release')
    disk=Path(a.disk_com).resolve()
    if not disk.is_file():raise ValueError('Missing DISK.COM')
    if disk.stat().st_size!=175:raise ValueError('Expected the generic 175-byte DISK.COM, not the old numeric selector')
    command_bytes=read_command_from_a(Path(a.boot_a))
    if a.hello and not Path(a.hello).is_file():raise ValueError('HELLO.TXT not found')
    print('Source files: 25 Descent + COMMAND.COM + DISK.COM' + (' + HELLO.TXT' if a.hello else ''))
    with template.open('rb') as f:
        if f.seek(0,2)!=BYTES: raise ValueError('Boot template must be 30 MiB (31,457,280 bytes)')
        f.seek(0);boot=f.read(512)
    if boot[510:512]!=b'\x55\xaa':raise ValueError('Boot template lacks signature')
    # Build a NEW blank filesystem using only boot sector/BPB, NEVER source FAT/data.
    img=bytearray(BYTES)
    img[:512]=boot
    fat=FAT16(img)
    if (fat.bps,fat.spc,fat.res,fat.nfat,fat.spfat,fat.roots,fat.tot)!=(512,4,1,2,64,512,61440):
        raise ValueError('Unexpected template geometry. Need (512,4,1,2,64,512,61440)')
    fat.setfat(0,0xFFF8);fat.setfat(1,0xFFFF)
    # Set FAT16 identification and superfloppy media byte consistently.
    img[21]=0xF8
    print('Created empty FAT16: 30 MiB, 2 FATs, 2 KiB clusters; no old allocation data copied')
    fat.mkdir('GAMES');fat.mkdir('GAMES/DESCENT');fat.mkdir('TOOLS')
    manifest={}
    def add(src,dest):
        raw=src.read_bytes();fat.importfile(src,dest)
        manifest[dest.upper()]={'size':len(raw),'sha256':sha(raw)}
        print(f'  {dest:<35} {fmt(len(raw)):>11} bytes')
    # Import extracted COMMAND.COM via temporary file without leaving any output in C:.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='bb-c30-') as temp:
        command_path=Path(temp)/'COMMAND.COM'
        command_path.write_bytes(command_bytes)
        add(command_path,'COMMAND.COM')
    add(disk,'DISK.COM')
    for name,src in sources.items():add(src,'GAMES/DESCENT/'+name)
    if a.hello:add(Path(a.hello),'TOOLS/HELLO.TXT')
    print('Verifying contents against staged source SHA-256 hashes...')
    for dest,v in manifest.items():
        _,ent=fat.resolve(dest)
        value=fat.filebytes(ent)
        if len(value)!=v['size'] or sha(value)!=v['sha256']:
            raise ValueError('READBACK MISMATCH: '+dest)
    print(f'  Verified {len(manifest)} files byte-for-byte')
    # Temporarily create only the *new* image (never change prior image); verify on-disk bytes.
    try:
        with out.open('xb') as f:
            f.write(img);f.flush();os.fsync(f.fileno())
        result=audit(out)
        checks={'FAT copies differ':not result['fat_copies_identical'],
                'broken chains':bool(result['problems']),
                'cross-linked clusters':bool(result['crosslinks']),
                'orphaned clusters':bool(result['orphan_clusters']),
                'invalid FAT entries':bool(result['raw_invalid'])}
        if any(checks.values()):
            raise ValueError('POSTWRITE FAT AUDIT FAILED: '+str([k for k,v in checks.items() if v]))
        if len([e for e in result['files'] if e['kind']=='FILE'])!=len(manifest):raise ValueError('Missing directory entries in saved image')
        print(f'PASS: no broken chains, cross-links, orphans, invalid FAT entries; FATs match')
        print(f'Free: {result["free_clusters"]*result["cluster_size"]:,} bytes')
        print(f'SUCCESS: {out} ({out.stat().st_size:,} bytes)')
        print('Existing SD image not modified. Keep backups. Test DOS DIR before any writes.')
    except BaseException:
        if out.exists():out.unlink()
        raise

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,FatError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
