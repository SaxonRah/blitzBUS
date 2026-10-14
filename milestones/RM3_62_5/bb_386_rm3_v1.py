#!/usr/bin/env python3
"""blitz86 RM3 — additive 386 FS/GS and real-mode 32-bit near control flow.

Extract all bundle files to C:\\blitzBUS, after installing RM0, RM1, RM2,
and bb_386_rm2_flash_sram_v1.py. Run:
  python .\\bb_386_rm3_v1.py selftest
  python .\\bb_386_rm3_v1.py probe
  python .\\bb_386_rm3_v1.py apply
  python .\\bb_386_rm3_v1.py verify
Restore RM3 BEFORE restoring the RM2 SRAM relocation layer.
No Git patches; SHA256-backed exact rollback. CPU=286 remains unchanged.
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

TAG = 'BB_386_RM3_V1'
HERE = Path(__file__).resolve().parent
BACKUP = HERE / '.bb_386_rm3_v1_backup'
EDITED = ['include/b86.h', 'src/interp.c', 'src/i386_rm1.inc']
CREATED = {'src/i386_rm3.inc': 'i386_rm3.inc',
           'tests/bb_386_rm3_smoke.c': 'bb_386_rm3_smoke.c'}


def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


def eol(data: bytes) -> str:
    if b'\r' in data.replace(b'\r\n', b''): raise RuntimeError('unsupported CR-only/mixed EOL')
    if b'\r\n' in data and b'\n' in data.replace(b'\r\n', b''):
        raise RuntimeError('mixed EOL')
    return '\r\n' if b'\r\n' in data else '\n'


def one(s: str, a: str, b: str, label: str) -> str:
    n = s.count(a)
    if n != 1: raise RuntimeError(f'{label}: expected 1 unique anchor, got {n}')
    return s.replace(a, b, 1)


def transform(rel: str, raw: bytes) -> bytes:
    nl = eol(raw)
    s = raw.decode('utf8').replace('\r\n', '\n')
    if TAG in s: raise RuntimeError(f'{rel}: already installed')
    if rel == 'include/b86.h':
        s = one(s, 'enum { B86_ES, B86_CS, B86_SS, B86_DS };',
                'enum { B86_ES, B86_CS, B86_SS, B86_DS };\n'
                f'/* {TAG}: extra segment selectors; do not renumber the native four. */\n'
                'enum { B86_FS = 4, B86_GS = 5 };', 'FS/GS constants')
        s = one(s, '} B86Cpu;',
                f'    /* {TAG}: appended only; old generated-code offsets unchanged. */\n'
                '    uint16_t seg386[2];   /* FS and GS selectors, real mode */\n'
                '} B86Cpu;', 'CPU tail fields')
    elif rel == 'src/i386_rm1.inc':
        n = s.count('c->seg[m->seg]')
        if n != 2: raise RuntimeError(f'RM1 FS/GS access anchor: expected 2, got {n}')
        s = f'/* {TAG}: FS/GS-compatible real-mode segment-value lookup. */\n' + s.replace(
            'c->seg[m->seg]', 'b86_rm3_segvalue(c, m->seg)')
    elif rel == 'src/interp.c':
        for x in ['BB_386_RM0_V1', 'BB_386_RM1_V1', 'BB_386_RM2_V1',
                  'BB_386_RM2_FLASH_SRAM_V1', '#include "i386_rm2.inc"']:
            if x not in s: raise RuntimeError(f'need current RM0/RM1/RM2/flash install: missing {x}')
        s = one(s, '#include "i386_rm1.inc"\n',
                f'/* {TAG}: forward selector accessor for RM1 memory helpers. */\n'
                'static uint32_t b86_rm3_segvalue(B86Cpu *c, int which);\n'
                '#include "i386_rm1.inc"\n', 'RM1 include')
        s = one(s, '#include "i386_rm2.inc"\n',
                '#include "i386_rm2.inc"\n'
                f'/* {TAG}: FS/GS and 32-bit near flow, XIP flash. */\n'
                '#include "i386_rm3.inc"\n', 'RM2 include')
        s = one(s,
                '        if (c->model >= B86_CPU_386 && op == 0x67) { address32 = 1; continue; }',
                '        if (c->model >= B86_CPU_386 && op == 0x67) { address32 = 1; continue; }\n'
                '        if (c->model >= B86_CPU_386 && (op == 0x64 || op == 0x65)) {\n'
                '            s->seg = op == 0x64 ? B86_FS : B86_GS; continue;\n'
                '        }', 'FS/GS prefix parsing')
        # Do not modify the old 8086/186/286 path: inside model>=386 only.
        s = one(s, '        /* RM2: 386-only 0F opcodes.',
                f'        /* {TAG}: intercept only new 386 encodings. */\n'
                '        { int r3 = b86_rm3_dispatch(s, op, operand32, address32);\n'
                '          if (r3 >= 0) return r3; }\n'
                '        /* RM2: 386-only 0F opcodes.', '386-only dispatch')
        s = one(s,
                '        if (op == 0x67 || op == 0x26 || op == 0x2E || op == 0x36 ||',
                '        if (op == 0x67 || op == 0x64 || op == 0x65 || op == 0x26 || op == 0x2E || op == 0x36 ||',
                '386 flash wrapper prefix recognition')
    else: raise RuntimeError('unexpected file ' + rel)
    return s.replace('\n', nl).encode('utf8')


def rootsafe(root: Path) -> None:
    for rel in EDITED:
        if not (root / rel).is_file(): raise RuntimeError('missing source '+str(root / rel))
    for name in CREATED.values():
        if not (HERE / name).is_file(): raise RuntimeError('missing bundle file '+name)
    if not (HERE / '.bb_386_rm2_flash_sram_v1_backup/manifest.json').is_file():
        # Normal local install. Allow isolated test root through --blitz86.
        if root == Path(r'C:\blitz86_v2'):
            raise RuntimeError('install the RM2 SRAM->Flash fix first')


def manifest(root: Path) -> dict:
    f = BACKUP / 'manifest.json'
    if not f.is_file(): raise RuntimeError('RM3 install manifest not found')
    m = json.loads(f.read_text('utf8'))
    if m.get('tag') != TAG or m.get('root') != str(root.resolve()):
        raise RuntimeError('RM3 manifest refers to another checkout')
    return m


def verify(root: Path) -> None:
    m = manifest(root)
    for rel, hashes in m['edited'].items():
        if sha((root / rel).read_bytes()) != hashes['after']:
            raise RuntimeError(f'RM3 edited source changed: {rel}')
        if sha((BACKUP / rel).read_bytes()) != hashes['before']:
            raise RuntimeError(f'RM3 backup changed: {rel}')
    for rel, h in m['created'].items():
        if sha((root / rel).read_bytes()) != h:
            raise RuntimeError(f'RM3 new file changed: {rel}')
    print('VERIFIED RM3: FS/GS, 32-bit near flow; pre-RM3 byte backups intact')


def probe(root: Path) -> None:
    rootsafe(root)
    if BACKUP.exists(): raise RuntimeError('RM3 backup exists; use verify')
    for rel in CREATED:
        if (root / rel).exists(): raise RuntimeError('refusing to overwrite '+rel)
    for rel in EDITED:
        raw = (root / rel).read_bytes()
        v = transform(rel, raw)
        print(f'{rel}: anchors PASS, {len(raw)} -> {len(v)} bytes, EOL={eol(raw)!r}')
    for rel in CREATED: print(rel+' will create')
    print('PROBE PASS — no files modified')


def apply(root: Path) -> None:
    probe(root)
    old = {rel: (root / rel).read_bytes() for rel in EDITED}
    new = {rel: transform(rel, buf) for rel, buf in old.items()}
    added = {rel: (HERE / f).read_bytes() for rel, f in CREATED.items()}
    obj = {'tag': TAG, 'root': str(root.resolve()),
           'edited': {rel: {'before': sha(old[rel]), 'after': sha(new[rel])} for rel in EDITED},
           'created': {rel: sha(buf) for rel, buf in added.items()}}
    BACKUP.mkdir()
    written = []
    try:
        for rel, buf in old.items():
            f = BACKUP / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(buf)
        (BACKUP / 'manifest.json').write_text(json.dumps(obj, indent=2)+'\n', encoding='utf8')
        for rel, buf in {**new, **added}.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(buf)
            written.append(rel)
        verify(root)
    except Exception:
        for rel in written:
            f = root / rel
            if rel in old: f.write_bytes(old[rel])
            else: f.unlink(missing_ok=True)
        shutil.rmtree(BACKUP)
        raise
    print('APPLIED RM3: new compatibility code in flash; 286 JIT unchanged')


def restore(root: Path) -> None:
    m = manifest(root)
    verify(root)
    for rel in EDITED:
        (root / rel).write_bytes((BACKUP / rel).read_bytes())
        if sha((root / rel).read_bytes()) != m['edited'][rel]['before']:
            raise RuntimeError('restore integrity error: '+rel)
    for rel in CREATED: (root / rel).unlink()
    shutil.rmtree(BACKUP)
    print('RESTORED RM3 byte-exactly; RM2/flash relocation, RM1/RM0 retained')


def selftest() -> None:
    global HERE, BACKUP
    oldhere, oldback = HERE, BACKUP
    sample = '''/* BB_386_RM0_V1 BB_386_RM1_V1 BB_386_RM2_V1 BB_386_RM2_FLASH_SRAM_V1 */
#include "i386_rm1.inc"
#include "i386_rm2.inc"
        if (c->model >= B86_CPU_386 && op == 0x67) { address32 = 1; continue; }
        /* RM2: 386-only 0F opcodes.
        if (op == 0x67 || op == 0x26 || op == 0x2E || op == 0x36 ||
'''
    head = 'enum { B86_ES, B86_CS, B86_SS, B86_DS };\n} B86Cpu;\n'
    rm1 = 'static void xx(B86Cpu *c,B86RM1EA*m){(void)c->seg[m->seg];(void)c->seg[m->seg];}\n'
    try:
        for nl in ['\n', '\r\n']:
            assert TAG.encode() in transform('src/interp.c', sample.replace('\n',nl).encode())
            assert TAG.encode() in transform('include/b86.h', head.replace('\n',nl).encode())
            assert TAG.encode() in transform('src/i386_rm1.inc', rm1.replace('\n',nl).encode())
        with tempfile.TemporaryDirectory() as d:
            HERE = Path(d)
            BACKUP = HERE / '.bb_386_rm3_v1_backup'
            for name in CREATED.values():
                (HERE / name).write_bytes((oldhere / name).read_bytes())
            # Exercise byte-exact rollback with BOTH newline encodings.
            # Path.write_text() performs platform-dependent newline translation
            # on Windows, so fixture inputs MUST be written as raw bytes.
            # This was the cause of the original Windows-only selftest failure;
            # the actual installer/restore logic already uses read/write_bytes.
            for nl, suffix in [ ('\n', 'lf'), ('\r\n', 'crlf') ]:
                root = HERE / ('checkout_' + suffix)
                fixtures = {
                    rel: source.replace('\n', nl).encode('utf8')
                    for rel, source in [('src/interp.c', sample),
                                        ('include/b86.h', head),
                                        ('src/i386_rm1.inc', rm1)]
                }
                for rel, raw in fixtures.items():
                    f = root / rel
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(raw)
                probe(root)
                apply(root)
                verify(root)
                restore(root)
                assert not BACKUP.exists(), f'{suffix}: backup not removed'
                for rel, raw in fixtures.items():
                    assert (root / rel).read_bytes() == raw, f'{suffix}: bad byte restore: {rel}'
                assert all(not (root / f).exists() for f in CREATED), f'{suffix}: created file remains'
    finally:
        HERE, BACKUP = oldhere, oldback
    print('SELFTEST PASS: anchors, LF/CRLF byte-exact install/verify/restore')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['selftest','probe','apply','verify','restore'])
    parser.add_argument('--blitz86', type=Path,
                        default=Path(r'C:\blitz86_v2') if os.name == 'nt' else HERE/'blitz86_v2')
    args = parser.parse_args()
    root = args.blitz86.resolve()
    if args.action == 'selftest': selftest()
    else: {'probe':probe,'apply':apply,'verify':verify,'restore':restore}[args.action](root)


if __name__ == '__main__':
    try: main()
    except (RuntimeError,ValueError,OSError,UnicodeError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        sys.exit(1)
