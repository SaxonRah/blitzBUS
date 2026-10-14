#!/usr/bin/env python3
"""Audit an MS-DOS 6.22 three-floppy set and stage it for blitzBUS IPL v1.

This tool does not contain or download MS-DOS. No boot sector is modified.
Disk 1 is selected as DOS622.IMG. Disks 2 and 3 are only staged;
IPL v1 does not yet implement hot-swapping.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile

SIZE = 1_474_560
IMAGES = ('dos-622-disk1.img', 'dos-622-disk2.img', 'dos-622-disk3.img')
TARGETS = ('DOS622.IMG', 'DOS622D2.IMG', 'DOS622D3.IMG')
SYSTEM_FILES = (b'IO      SYS', b'MSDOS   SYS', b'COMMAND COM')


def le16(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off:off + 2], 'little')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for buf in iter(lambda: f.read(131072), b''):
            h.update(buf)
    return h.hexdigest()


def inspect_image(path: Path, disk_number: int) -> dict:
    if not path.is_file():
        raise ValueError(f'Disk {disk_number} not found: {path}')
    nbytes = path.stat().st_size
    if nbytes != SIZE:
        raise ValueError(f'Disk {disk_number}: expected {SIZE} bytes, got {nbytes}')
    # Disk auditing loads only the first few FAT and root sectors.
    with path.open('rb') as f:
        boot = f.read(512)
        if len(boot) != 512:
            raise ValueError(f'Disk {disk_number}: short boot sector')
        expected = {
            'bytes/sector': (le16(boot, 11), 512),
            'sectors/cluster': (boot[13], 1),
            'reserved sectors': (le16(boot, 14), 1),
            'FAT count': (boot[16], 2),
            'root entries': (le16(boot, 17), 224),
            'total sectors': (le16(boot, 19), 2880),
            'media byte': (boot[21], 0xF0),
            'sectors/FAT': (le16(boot, 22), 9),
            'sectors/track': (le16(boot, 24), 18),
            'heads': (le16(boot, 26), 2),
        }
        problems = [f'{label} is {got}, expected {want}'
                    for label, (got, want) in expected.items() if got != want]
        if boot[510:512] != b'\x55\xAA':
            problems.append('boot signature 55 AA missing')
        if disk_number == 1 and boot[0] not in (0xEB, 0xE9):
            problems.append('Disk 1 boot sector does not start with JMP')
        root_start = (le16(boot, 14) + boot[16] * le16(boot, 22)) * 512
        root_length = le16(boot, 17) * 32
        if root_start + root_length > SIZE:
            problems.append('root directory beyond end of image')
            entries, label = {}, ''
        else:
            f.seek(root_start)
            data = f.read(root_length)
            entries, label = {}, ''
            for off in range(0, len(data), 32):
                e = data[off:off + 32]
                if e[0] == 0:
                    break
                if e[0] == 0xE5 or e[11] == 0x0F:
                    continue
                if e[11] & 0x08:  # Volume label
                    label = e[:11].decode('ascii', 'replace').strip()
                    continue
                if e[11] & 0x10:  # Subdirectory
                    continue
                entries[e[:11]] = int.from_bytes(e[28:32], 'little')
        if disk_number == 1:
            for item in SYSTEM_FILES:
                if item not in entries:
                    problems.append(f'Disk 1 missing {item.decode("ascii").strip()}')
                elif entries[item] == 0:
                    problems.append(f'Disk 1 has empty {item.decode("ascii").strip()}')
        if problems:
            raise ValueError(f'{path}:\n  ' + '\n  '.join(problems))
        return {'path': path, 'disk': disk_number, 'label': label,
                'files': len(entries), 'sha256': sha256_file(path),
                'boot_oem': boot[3:11].decode('ascii', 'replace').strip(),
                'system_files': {k.decode('ascii').strip(): entries.get(k)
                                 for k in SYSTEM_FILES} if disk_number == 1 else {}}


def atomic_copy_verified(src: Path, dst: Path, digest: str, replace: bool) -> str:
    if dst.exists() and sha256_file(dst) == digest:
        return 'already identical'
    if dst.exists() and not replace:
        raise ValueError(f'{dst} already exists with different bytes; pass --replace to overwrite')
    # Temporary file is created beside destination so os.replace is atomic.
    fd, name = tempfile.mkstemp(prefix='.bb-dos622-', suffix='.tmp', dir=dst.parent)
    try:
        with os.fdopen(fd, 'wb') as out, src.open('rb') as source:
            shutil.copyfileobj(source, out, length=131072)
            out.flush()
            os.fsync(out.fileno())
        staged = Path(name)
        if sha256_file(staged) != digest:
            raise ValueError(f'checksum mismatch writing {dst.name}')
        os.replace(staged, dst)
        return 'copied and SHA-256 verified'
    finally:
        if os.path.exists(name):
            os.unlink(name)


def stage_three(source: Path, sd_dir: Path | None, replace: bool = False) -> list[dict]:
    details = [inspect_image(source / filename, i + 1) for i, filename in enumerate(IMAGES)]
    for i, item in enumerate(details):
        print(f'Disk {i+1}: {IMAGES[i]} | {item["files"]} files | label="{item["label"]}" '
              f'| OEM="{item["boot_oem"]}"')
        print(f'  SHA256 {item["sha256"]}')
        if i == 0:
            for name, length in item['system_files'].items():
                print(f'  {name}: {length} bytes')
    if sd_dir is None:
        print('AUDIT PASS: three FAT12 images validated; nothing copied.')
        return details
    if not sd_dir.is_dir() or sd_dir.name.upper() != 'BLITZBUS':
        raise ValueError(f'--sd-dir must point to an existing BLITZBUS folder: {sd_dir}')
    if not (sd_dir / 'BOOT.IMG').is_file():
        print('WARNING: BOOT.IMG not found; existing DOS 2 fallback may be unavailable.', file=sys.stderr)
    # Fail before mutating anything if there is a destination conflict.
    for dst_name, item in zip(TARGETS, details):
        dst = sd_dir / dst_name
        if dst.exists() and sha256_file(dst) != item['sha256'] and not replace:
            raise ValueError(f'{dst} differs; add --replace to overwrite this image')
    for dst_name, item in zip(TARGETS, details):
        dest = sd_dir / dst_name
        status = atomic_copy_verified(item['path'], dest, item['sha256'], replace)
        print(f'{dest}: {status}')
    # Activate alternate boot only after all images are durably staged.
    (sd_dir / 'DOS622.TXT').write_bytes(b'1\n')
    print('DOS622.TXT set to 1: real DOS 6.22 floppy boot enabled on next restart.')
    print('IMPORTANT: IPL v1 reads only DOS622.IMG (Disk 1); Disk 2/3 swapping is not supported yet.')
    return details


def selftest() -> None:
    def make_disk(path: Path, number: int):
        data = bytearray(SIZE)
        data[0:3] = b'\xEB\x3C\x90'
        data[3:11] = b'MSDOS622'
        data[11:13] = (512).to_bytes(2, 'little')
        data[13] = 1
        data[14:16] = (1).to_bytes(2, 'little')
        data[16] = 2
        data[17:19] = (224).to_bytes(2, 'little')
        data[19:21] = (2880).to_bytes(2, 'little')
        data[21] = 0xF0
        data[22:24] = (9).to_bytes(2, 'little')
        data[24:26] = (18).to_bytes(2, 'little')
        data[26:28] = (2).to_bytes(2, 'little')
        data[510:512] = b'\x55\xAA'
        root = 19 * 512
        names = SYSTEM_FILES if number == 1 else (b'SETUP   IN_',)
        for index, name in enumerate(names):
            off = root + index * 32
            data[off:off+11] = name
            data[off + 11] = 0x06 if number == 1 else 0x20
            data[off + 26:off + 28] = (index + 2).to_bytes(2, 'little')
            data[off + 28:off + 32] = (100 + index).to_bytes(4, 'little')
        path.write_bytes(data)

    with tempfile.TemporaryDirectory(prefix='bbdos622-test-') as temporary:
        root = Path(temporary)
        source = root / 'source'; source.mkdir()
        target = root / 'BLITZBUS'; target.mkdir()
        (target / 'BOOT.IMG').write_bytes(b'keep existing DOS2')
        for i, f in enumerate(IMAGES):
            make_disk(source / f, i+1)
        stage_three(source, None)
        stage_three(source, target)
        for filename, dest in zip(IMAGES, TARGETS):
            assert (source / filename).read_bytes() == (target / dest).read_bytes()
        assert (target / 'DOS622.TXT').read_bytes() == b'1\n'
        stage_three(source, target)
        (target / 'DOS622D2.IMG').write_bytes(b'collision')
        try:
            stage_three(source, target)
        except ValueError as e:
            assert '--replace' in str(e)
        else:
            raise AssertionError('conflicting destination was not rejected')
        stage_three(source, target, replace=True)
        assert (target / 'DOS622D2.IMG').read_bytes() == (source / IMAGES[1]).read_bytes()
        assert (target / 'BOOT.IMG').read_bytes() == b'keep existing DOS2'
        bad = source / IMAGES[0]
        with bad.open('r+b') as f:
            f.seek(510); f.write(b'\0\0')
        try:
            stage_three(source, None)
        except ValueError as e:
            assert 'signature' in str(e)
        else:
            raise AssertionError('bad boot signature was not rejected')
    print('SELFTEST PASS: 3 image validation, collision refusal, SHA verification, replacement, DOS2 preservation')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=Path(r'C:\dos622'),
                        help=r'Folder containing dos-622-disk1.img, disk2.img, disk3.img (default C:\dos622)')
    parser.add_argument('--sd-dir', type=Path,
                        help=r'Existing SD card BLITZBUS directory, e.g. G:\BLITZBUS')
    parser.add_argument('--replace', action='store_true',
                        help='Allow overwriting existing DOS622 image files with different bytes')
    parser.add_argument('--selftest', action='store_true', help='Test with synthetic FAT12 images')
    args = parser.parse_args()
    try:
        if args.selftest:
            selftest()
        else:
            stage_three(args.source_dir, args.sd_dir, args.replace)
    except (OSError, ValueError) as e:
        print('ERROR:', e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
