#!/usr/bin/env python3
"""Validate and optionally stage a user-supplied bootable MS-DOS 6.x floppy.
No proprietary DOS binary, DOS boot sector, or system files are included.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import shutil
import sys

SIZE = 1_474_560
NAMES = (b'IO      SYS', b'MSDOS   SYS', b'COMMAND COM')

def check_image(path: Path, verbose: bool = True) -> dict:
    if not path.is_file(): raise ValueError(f'Image not found: {path}')
    data = path.read_bytes()
    errors = []
    if len(data) != SIZE: raise ValueError(f'Expected a 1,474,560-byte 1.44MB floppy, got {len(data)} bytes')
    bs = data[:512]
    b16 = lambda at: int.from_bytes(bs[at:at+2], 'little')
    if bs[510:512] != b'\x55\xaa': errors.append('Missing 55 AA boot signature')
    if bs[0] not in (0xeb, 0xe9): errors.append('No x86 JMP at boot-sector entry')
    expected = {'bytes/sector': (b16(11),512), 'sectors/cluster': (bs[13],1),
                'reserved sectors': (b16(14),1), 'FAT count': (bs[16],2),
                'root entries': (b16(17),224), 'total sectors': (b16(19),2880),
                'sectors/FAT': (b16(22),9), 'sectors/track': (b16(24),18),
                'heads': (b16(26),2)}
    for name, (actual, wanted) in expected.items():
        if actual != wanted: errors.append(f'{name}: expected {wanted}, got {actual}')
    root_start = (b16(14) + bs[16] * b16(22)) * 512
    root_end = root_start + bs[17] * 32
    entries = {}
    if 0 <= root_start <= root_end <= len(data):
        for off in range(root_start, root_end, 32):
            e = data[off:off+32]
            if e[0] == 0: break
            if e[0] == 0xe5 or e[11] & 0x18: continue
            entries[e[:11]] = {'cluster':int.from_bytes(e[26:28],'little'),
                               'size':int.from_bytes(e[28:32],'little'),
                               'attributes':e[11]}
    else: errors.append('Root directory outside disk image')
    for name in NAMES:
        if name not in entries: errors.append(f'Missing {name.decode("ascii").strip()} root-directory file')
        elif entries[name]['size'] <= 0: errors.append(f'Zero length {name.decode("ascii")}')
    if verbose:
        print(f'Image: {path}')
        print(f'SHA256: {hashlib.sha256(data).hexdigest()}')
        print(f'Boot OEM field: {bs[3:11].decode("ascii", "replace")}')
        for name in NAMES:
            print(f'  {name.decode("ascii")}: {entries.get(name,"MISSING")}')
        for err in errors: print(f'  ERROR: {err}')
        print('Structural boot candidate: '+('PASS' if not errors else 'FAIL'))
        print('NOTE: These checks do NOT authenticate the DOS release or prove the disk boots.')
    if errors: raise ValueError('; '.join(errors))
    return {'sha256':hashlib.sha256(data).hexdigest(), 'root':entries}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image', type=Path, help='Your original bootable DOS 6.22 1.44MB .IMG')
    ap.add_argument('--sd-dir',type=Path,help='Path to the SD card BLITZBUS directory, e.g. G:\\BLITZBUS')
    ap.add_argument('--replace', action='store_true', help='Overwrite existing DOS622.IMG in staging directory')
    args=ap.parse_args()
    try:
        result=check_image(args.image)
        if args.sd_dir:
            if not args.sd_dir.is_dir(): raise ValueError(f'Directory does not exist: {args.sd_dir}')
            if args.sd_dir.name.upper() != 'BLITZBUS':
                raise ValueError('Please supply the SD card BLITZBUS folder (not the SD root)')
            dest=args.sd_dir/'DOS622.IMG'
            if dest.exists() and not args.replace:
                raise ValueError(f'{dest} exists; use --replace to overwrite')
            if args.image.resolve() != dest.resolve():
                shutil.copyfile(args.image, dest)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != result['sha256']:
                raise ValueError('Staged image checksum mismatch')
            (args.sd_dir/'DOS622.TXT').write_bytes(b'1\n')
            print('Staged read-only guest image: '+str(dest))
            print('Boot selection: '+str(args.sd_dir/'DOS622.TXT'))
    except (ValueError, OSError) as ex:
        print('ERROR: '+str(ex), file=sys.stderr); return 1
    return 0

if __name__=='__main__': sys.exit(main())
