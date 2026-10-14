#!/usr/bin/env python3
"""Check exact images requested by the live DOS 6.22 A: swap firmware.
Read-only by default. Optional --stage-from copies a specified *existing*
DOS 6.22 floppy image to the exact requested name, safely and without overwrite.
"""
from __future__ import annotations
import argparse, hashlib, os, shutil, sys, tempfile
from pathlib import Path
SIZE = 1474560

def required_name(n: int) -> str:
    return 'DOS622.IMG' if n == 1 else f'DOS622{n}.IMG'

def sd_folder(raw: Path) -> Path:
    if (raw/'BLITZBUS').is_dir():
        return raw/'BLITZBUS'
    return raw

def digest(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as fd:
        while (b:=fd.read(65536)): h.update(b)
    return h.hexdigest()

def fat12_errors(path: Path) -> list[str]:
    size=path.stat().st_size
    if size!=SIZE: return [f'{size:,} bytes (expected {SIZE:,})']
    with path.open('rb') as fd: b=fd.read(512)
    errors=[]
    tests=[(b[510:512]==b'\x55\xaa','sector 0 signature 55AA'),
      (b[0] in (0xeb,0xe9),'boot JMP EB/E9'),
      (int.from_bytes(b[11:13],'little')==512,'512 bytes/sector'),
      (b[13]==1,'1 sector/cluster'),
      (int.from_bytes(b[14:16],'little')==1,'1 reserved sector'),
      (b[16]==2,'2 FATs'),
      (int.from_bytes(b[17:19],'little')==224,'224 root entries'),
      (int.from_bytes(b[19:21],'little')==2880,'2880 total sectors'),
      (int.from_bytes(b[22:24],'little')==9,'9 sectors/FAT'),
      (int.from_bytes(b[24:26],'little')==18,'18 sectors/track'),
      (int.from_bytes(b[26:28],'little')==2,'2 heads')]
    for passed,name in tests:
        if not passed: errors.append(name)
    return errors

def root_names(path: Path) -> list[str]:
    found=[]
    with path.open('rb') as fd:
        fd.seek(19*512)
        for _ in range(224):
            e=fd.read(32)
            if len(e)!=32 or e[0]==0:break
            if e[0]==0xe5 or e[11]&0x18: continue
            name=e[:8].decode('cp437','replace').strip()
            ext=e[8:11].decode('cp437','replace').strip()
            found.append(name+('.'+ext if ext else ''))
    return found

def near(directory:Path, target:str) -> list[str]:
    all_files=[p for p in directory.iterdir() if p.is_file()]
    matches=[]
    for p in all_files:
        name=p.name.upper()
        if name.startswith(('DOS622','MSDOS','DISK','SETUP')) and (name.endswith(('.IMG','.IMA','.DSK')) or name=='DOS6222'):
            matches.append(p.name)
    return sorted(matches, key=str.upper)

def audit(directory:Path, n:int) -> bool:
    if not directory.is_dir(): raise ValueError(f'No SD BLITZBUS directory: {directory}')
    wanted=required_name(n)
    print('Pico A: firmware opens:',f'0:/BLITZBUS/{wanted}')
    print('Expected Windows path:', directory/wanted)
    candidates={p.name.upper():p for p in directory.iterdir() if p.is_file()}
    p=candidates.get(wanted.upper())
    if not p:
        print('RESULT: MISSING (FatFs FR_NO_FILE=4 matches your hardware log)')
        ns=near(directory,wanted)
        if ns:print('Relevant existing files:',', '.join(ns))
        print('Use an actual MS-DOS 6.22 Setup Disk #'+str(n)+' image, not a renamed copy of Disk #1.')
        return False
    print('FOUND:',p.name,'size=',p.stat().st_size)
    errors=fat12_errors(p)
    if errors:
        print('RESULT: PRESENT BUT FIRMWARE-REJECTED:', '; '.join(errors))
        return False
    print('FAT12 boot sector: valid')
    print('SHA256:',digest(p))
    print('Root entries:',', '.join(root_names(p)[:16]) or '<empty>')
    first=candidates.get('DOS622.IMG')
    if n>1 and first:
        if digest(p)==digest(first):
            print('RESULT: INVALID DISK IDENTITY: bit-identical to DOS622.IMG (Disk #1).')
            return False
        print('Distinct from DOS622.IMG: yes')
    print('RESULT: FILE READY. Safely eject SD before Pico boot; live swapping requires current card contents.')
    return True

def stage(src:Path,directory:Path,n:int):
    if not src.is_file():raise ValueError(f'No source floppy image: {src}')
    if not directory.is_dir():raise ValueError(f'No BLITZBUS folder: {directory}')
    dst=directory/required_name(n)
    if dst.exists():raise ValueError('Target already exists; refusing to overwrite '+str(dst))
    errs=fat12_errors(src)
    if errs:raise ValueError('Source invalid for A: firmware: '+', '.join(errs))
    if n>1:
        first=directory/'DOS622.IMG'
        if first.is_file() and digest(src)==digest(first):
            raise ValueError('Source is IDENTICAL to Disk #1; refusing to copy it as Disk #'+str(n))
    with tempfile.NamedTemporaryFile(prefix='bb622stage-',suffix='.tmp',dir=directory,delete=False) as tmp:
        name=Path(tmp.name)
        try:
            with src.open('rb') as fd:shutil.copyfileobj(fd,tmp,length=65536)
            tmp.flush();os.fsync(tmp.fileno())
        except BaseException:
            name.unlink(missing_ok=True);raise
    try:
        if digest(name)!=digest(src):raise ValueError('staged bytes differ from source')
        # The caller already chose the destination and it was absent. Do not replace it.
        if dst.exists():raise ValueError('Target appeared during copy: '+str(dst))
        name.rename(dst)
    finally:name.unlink(missing_ok=True)
    print('STAGED source disk image to:',dst)
    print('SHA256 verified:',digest(dst))

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('sd',type=Path,help=r'SD root E:\ or BLITZBUS folder E:\BLITZBUS')
    ap.add_argument('--disk',type=int,default=2,choices=range(1,10))
    ap.add_argument('--stage-from',type=Path,help='Optional source disk-image file to copy into the SD folder without overwrite')
    a=ap.parse_args(argv)
    dir=sd_folder(a.sd)
    try:
        if a.stage_from:stage(a.stage_from,dir,a.disk)
        return 0 if audit(dir,a.disk) else 2
    except (OSError,ValueError) as exc:
        print('ERROR:',exc);return 1
if __name__=='__main__':sys.exit(main())
