#!/usr/bin/env python3
"""RM2 — 386 real-mode 0F instructions, layered reversible source installer.

Extract the *whole* ZIP to C:\blitzBUS and use:
  python bb_386_rm2_v1.py selftest
  python bb_386_rm2_v1.py probe
  python bb_386_rm2_v1.py apply
  python bb_386_rm2_v1.py verify
  python bb_386_rm2_v1.py restore

Required: installed RM0 and RM1. Modifies only src/interp.c;
adds src/i386_rm2.inc and tests/bb_386_rm2_smoke.c. No patch files.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

TAG = 'BB_386_RM2_V1'
HOME = Path(__file__).resolve().parent
BACKUP = HOME / '.bb_386_rm2_v1_backup'
EDITED = 'src/interp.c'
CREATED = {'src/i386_rm2.inc': 'i386_rm2.inc',
           'tests/bb_386_rm2_smoke.c': 'bb_386_rm2_smoke.c'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_end(data: bytes) -> str:
    if b'\r\n' in data:
        if b'\n' in data.replace(b'\r\n', b''):
            raise RuntimeError('mixed line endings')
        return '\r\n'
    return '\n'


def exactly_one(s: str, old: str, new: str, label: str) -> str:
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f'{label}: expected 1 occurrence, got {n}; no files changed')
    return s.replace(old, new, 1)


def transform(before: bytes) -> bytes:
    nl = line_end(before)
    s = before.decode('utf-8').replace('\r\n', '\n')
    if TAG in s:
        raise RuntimeError('RM2 already present; use verify')
    if 'BB_386_RM1_V1' not in s or 'BB_386_RM0_V1' not in s:
        raise RuntimeError('RM0 and RM1 must already be installed')
    s = exactly_one(
        s, '#include "i386_rm1.inc"\n',
        '#include "i386_rm1.inc"\n'
        f'/* {TAG}: 80386 real-mode extended 0F decoder, flash-only. */\n'
        '#include "i386_rm2.inc"\n', 'RM1 include')
    s = exactly_one(
        s, '        if (address32) return b86_rm1_67(s, op, operand32); /* 67h with optional 66h */\n',
        '        /* RM2: 386-only 0F opcodes. The 286 0F 01/06 cases stay on\n'
        '           their existing descriptor/MSW/CLTS interpreter path. */\n'
        '        if (op == 0x0F) {\n'
        '            uint8_t op2 = rd8(c, B86_CS, s->ip);\n'
        '            if (op2 != 0x01 && op2 != 0x06)\n'
        '                return b86_rm2_0f(s, operand32, address32);\n'
        '        }\n'
        '        if (address32) return b86_rm1_67(s, op, operand32); /* 67h with optional 66h */\n',
        '386 0F diversion')
    return s.replace('\n', nl).encode('utf-8')


def backup_path() -> Path:
    return BACKUP / 'manifest.json'


def guard(root: Path) -> None:
    for f in ('include/b86.h', 'src/interp.c', 'src/i386_rm0.inc', 'src/i386_rm1.inc'):
        if not (root / f).is_file():
            raise RuntimeError('expected RM0/RM1 source missing: ' + f)
    if b'B86_CPU_386' not in (root / 'include/b86.h').read_bytes():
        raise RuntimeError('missing 386 model declaration')


def get_manifest(root: Path) -> dict:
    if not backup_path().is_file():
        raise RuntimeError('RM2 not installed, or backup not found')
    obj = json.loads(backup_path().read_text(encoding='utf-8'))
    if obj.get('tag') != TAG or obj.get('root') != str(root.resolve()):
        raise RuntimeError('RM2 backup belongs to a different checkout')
    return obj


def verify(root: Path) -> None:
    m = get_manifest(root)
    for rel, checks in m['edited'].items():
        if sha((root / rel).read_bytes()) != checks['after']:
            raise RuntimeError('source changed since install, refusing restore: ' + rel)
        if sha((BACKUP / rel).read_bytes()) != checks['before']:
            raise RuntimeError('original backup changed: ' + rel)
    for rel, digest in m['created'].items():
        if sha((root / rel).read_bytes()) != digest:
            raise RuntimeError('installed file changed: ' + rel)
    print('VERIFIED RM2: 0F decoder installed, byte-identical rollback intact')


def probe(root: Path) -> None:
    guard(root)
    if BACKUP.exists():
        print('RM2 backup already exists; use verify instead')
        return
    orig = (root / EDITED).read_bytes()
    updated = transform(orig)
    print(f'{EDITED}: anchors PASS, {len(orig)} -> {len(updated)} bytes, newline={line_end(orig)!r}')
    for rel, name in CREATED.items():
        if (root / rel).exists():
            raise RuntimeError('refusing to overwrite: ' + rel)
        if not (HOME / name).is_file():
            raise RuntimeError('missing bundle file: ' + name)
        print(rel, 'will create')
    print('PROBE PASS — no files written')


def apply(root: Path) -> None:
    guard(root)
    if BACKUP.exists():
        raise RuntimeError('already installed or stale backup; verify before proceeding')
    probe(root)
    orig = (root / EDITED).read_bytes()
    updated = transform(orig)
    created = {rel: (HOME / filename).read_bytes() for rel, filename in CREATED.items()}
    manifest = {'tag': TAG, 'root': str(root.resolve()),
                'edited': {EDITED: {'before': sha(orig), 'after': sha(updated)}},
                'created': {rel: sha(data) for rel, data in created.items()}}
    BACKUP.mkdir()
    (BACKUP / 'src').mkdir()
    (BACKUP / EDITED).write_bytes(orig)
    backup_path().write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    written = []
    try:
        (root / EDITED).write_bytes(updated)
        written.append(EDITED)
        for rel, data in created.items():
            (root / rel).parent.mkdir(exist_ok=True, parents=True)
            (root / rel).write_bytes(data)
            written.append(rel)
        verify(root)
    except Exception:
        for rel in written:
            if rel == EDITED:
                (root / rel).write_bytes(orig)
            else:
                (root / rel).unlink(missing_ok=True)
        shutil.rmtree(BACKUP)
        raise
    print('APPLIED RM2; old 286 JIT and 232-KiB SRAM cache untouched')


def restore(root: Path) -> None:
    m = get_manifest(root)
    verify(root)
    (root / EDITED).write_bytes((BACKUP / EDITED).read_bytes())
    if sha((root / EDITED).read_bytes()) != m['edited'][EDITED]['before']:
        raise RuntimeError('rollback verification failed')
    for rel in CREATED:
        (root / rel).unlink()
    shutil.rmtree(BACKUP)
    print('RESTORED RM2 exactly; RM1/RM0/RCX/eager-unchaining retained')


def selftest() -> None:
    src = ('/* BB_386_RM0_V1 */\n/* BB_386_RM1_V1 */\n'
           '#include "i386_rm1.inc"\n'
           '        if (address32) return b86_rm1_67(s, op, operand32); /* 67h with optional 66h */\n')
    for nl in ('\n', '\r\n'):
        b = src.replace('\n', nl).encode('utf-8')
        result = transform(b)
        assert TAG.encode() in result
        assert line_end(result) == nl
        assert result == transform(b)
        assert len(result) > len(b)
    global HOME, BACKUP
    oldhome, oldback = HOME, BACKUP
    try:
        with tempfile.TemporaryDirectory() as temp:
            HOME = Path(temp)
            BACKUP = HOME / '.bb_386_rm2_v1_backup'
            checkout = HOME / 'checkout'
            (checkout / 'src').mkdir(parents=True)
            (checkout / 'include').mkdir()
            (checkout / 'tests').mkdir()
            (checkout / 'src/interp.c').write_bytes(src.encode())
            (checkout / 'src/i386_rm0.inc').write_text('/* RM0 */')
            (checkout / 'src/i386_rm1.inc').write_text('/* RM1 */')
            (checkout / 'include/b86.h').write_text('B86_CPU_386')
            for file in CREATED.values():
                (HOME / file).write_bytes((oldhome / file).read_bytes())
            probe(checkout)
            apply(checkout)
            restore(checkout)
            assert (checkout / 'src/interp.c').read_bytes() == src.encode()
            assert all(not (checkout / rel).exists() for rel in CREATED)
            assert not BACKUP.exists()
    finally:
        HOME, BACKUP = oldhome, oldback
    print('SELFTEST PASS: LF/CRLF, unique anchors, install/verify/exact restore')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['selftest', 'probe', 'apply', 'verify', 'restore'])
    ap.add_argument('--blitz86', type=Path,
                    default=(Path(r'C:\blitz86_v2') if os.name == 'nt' else HOME / 'blitz86_v2'))
    args = ap.parse_args()
    if args.action == 'selftest':
        selftest()
        return
    root = args.blitz86.resolve()
    {'probe': probe, 'apply': apply, 'verify': verify, 'restore': restore}[args.action](root)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(1)
