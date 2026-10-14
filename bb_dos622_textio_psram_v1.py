#!/usr/bin/env python3
"""Restore Pico SRAM headroom in DOS 6.22 text-mode USB console stage.

Complete-file, transactional installer; no Git patches.  Requires installed
textio v1 plus its seven earlier stages; preserves byte-exact backup manifests.
Commands: selftest | probe | apply | verify | restore.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import bb_dos622_textio_v1 as parent

HERE = Path(__file__).resolve().parent
TAG = 'BB_DOS622_TEXTIO_PSRAM_V1'
STATE = '.bb_dos622_textio_psram_v1_state'
SRC = parent.SRC
INC = parent.INC
TEXTIO = parent.STATE + '/manifest.json'
PARENTS = (*parent.PARENTS, TEXTIO)
BASE_INC_SHA = '597a78546d98f274'  # textio v1 include supplied with the previous stage

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def jd(obj: dict) -> bytes:
    return json.dumps(obj, indent=2).encode('utf-8')

def source_transform(before: bytes) -> bytes:
    if TAG.encode('ascii') in before or b'bb622_textio_reset();' in before:
        raise ValueError('textio PSRAM recovery already present')
    # A line unique to the installed DOS622 startup; insert reset *before*
    # the image boots, not at the first screen sample (PSRAM is uninitialized).
    pat = rb'(?m)^(?P<indent>[ \t]*)bb_v15_original_interrupt = bb622_bios_interrupt;(?P<nl>\r\n|\n|\r|$)'
    matches = list(re.finditer(pat, before))
    if len(matches) != 1:
        raise ValueError(f'expected exactly one DOS622 BIOS-hook anchor; found {len(matches)}')
    m = matches[0]
    nl = m.group('nl') or b'\n'
    addition = m.group('indent') + b'bb622_textio_reset(); /* BB_DOS622_TEXTIO_PSRAM_V1 */' + nl
    return before[:m.end()] + addition + before[m.end():]

def plan(root: Path, new_inc: bytes) -> dict:
    if (root / STATE).exists():
        raise ValueError('PSRAM recovery already installed; use verify/restore')
    parent.verify(root, quiet=True)
    if b'BB_DOS622_TEXTIO_PSRAM_V1' not in new_inc:
        raise ValueError('replacement include is not the PSRAM implementation')
    old = {p: (root/p).read_bytes() for p in (SRC, INC, *PARENTS)}
    if sha(old[INC])[:16] != BASE_INC_SHA:
        raise ValueError(f'textio source not original v1; expected {BASE_INC_SHA}, got {sha(old[INC])[:16]}')
    changed = {SRC: source_transform(old[SRC]), INC: new_inc}
    # All previous manifests track the same source digests and often also
    # track manifests before them.  Regenerate from earliest to latest.
    for p in PARENTS:
        obj = copy.deepcopy(json.loads(old[p]))
        for tracked, entry in obj.get('files', {}).items():
            if tracked in changed:
                for key in ('installed', 'new', 'after'):
                    if key in entry:
                        entry[key] = sha(changed[tracked])
        if p == parent.rtc.DIAG:
            obj['parent_after'] = sha(changed[parent.rtc.IPL])
        changed[p] = jd(obj)
    changes = {p: (old[p], changed[p]) for p in (SRC, INC, *PARENTS)}
    return changes

def verify(root: Path, quiet: bool = False):
    meta = json.loads((root/STATE/'manifest.json').read_text(encoding='utf-8'))
    if meta.get('tag') != TAG: raise ValueError('wrong recovery manifest tag')
    for p, ent in meta['files'].items():
        if sha((root/p).read_bytes()) != ent['new']:
            raise ValueError(f'installed SHA mismatch: {p}')
        if sha((root/STATE/ent['backup']).read_bytes()) != ent['old']:
            raise ValueError(f'original backup SHA mismatch: {p}')
    parent.verify(root, quiet=True)
    src = (root/SRC).read_bytes()
    inc = (root/INC).read_bytes()
    if src.count(b'bb622_textio_reset(); /* BB_DOS622_TEXTIO_PSRAM_V1 */') != 1:
        raise ValueError('missing PSRAM startup initialization')
    if inc.count(b'__uninitialized_psram("bb622_textio")') != 1:
        raise ValueError('PSRAM section not found in textio include')
    if not quiet:
        print('VERIFIED: DOS622 PSRAM textio state, initialization, exact backups, and eight parent manifest chains')

def apply(root: Path, new_inc: bytes):
    changes = plan(root, new_inc)
    state = root/STATE
    state.mkdir()
    try:
        meta = {'tag': TAG, 'files': {}}
        for i, (p, (old, new)) in enumerate(changes.items()):
            bak = f'original_{i:02d}.bin'
            (state/bak).write_bytes(old)
            meta['files'][p] = {'old': sha(old), 'new': sha(new), 'backup': bak}
        (state/'manifest.json').write_bytes(jd(meta))
        for p, (old, new) in changes.items():
            dest = root/p
            if dest.read_bytes() != old:
                raise ValueError(f'concurrent source change: {p}')
            dest.write_bytes(new)
        verify(root, quiet=True)
    except BaseException:
        for p, (old, _) in changes.items():
            (root/p).write_bytes(old)
        shutil.rmtree(state, ignore_errors=True)
        raise
    print('APPLIED: textio bookkeeping moved from SRAM to PSRAM; reset before DOS622 boot; CPU and JIT untouched')

def restore(root: Path):
    verify(root, quiet=True)
    state = root/STATE
    meta = json.loads((state/'manifest.json').read_text(encoding='utf-8'))
    for p, ent in meta['files'].items():
        (root/p).write_bytes((state/ent['backup']).read_bytes())
    shutil.rmtree(state)
    parent.verify(root, quiet=True)
    print('RESTORED: original textio include, live source, and all parent manifests byte-exact')

def selftest(new_inc: bytes):
    original_inc = (HERE/'bb_dos622_textio_v1_original.inc').read_bytes()
    fixture = (b'''static void bb_v23_poll_input(void) {\n    if(!bb_video_seen||!R)return;\n    ++bb_v23_polls;\n}\nstatic int bb_v22_keyboard(void) {\n    bb_v23_poll_input();\n    return 1;\n}\n'''
               b'''static int start(MdRuntime *rt) {\n'''
               b'''    if (bb_sd_dos622_active()) {\n'''
               b'''        bb_v15_original_interrupt = bb622_bios_interrupt;\n'''
               b'''    }\n    return 1;\n}\n'''
               b'''B86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)\n{\n'''
               b'''    if (R == NULL && !start(rt)) return 0;\n'''
               b'''    bb_v23_poll_input();\n    return 1;\n}\n''')
    variants = (
        ('LF',fixture),
        ('CRLF',fixture.replace(b'\n',b'\r\n')),
        ('MIXED',fixture.replace(b'        bb_v15_original_interrupt = bb622_bios_interrupt;\n',b'        bb_v15_original_interrupt = bb622_bios_interrupt;\r\n')),
        ('CRLF_WITH_LF_BIOS',fixture.replace(b'\n',b'\r\n').replace(b'        bb_v15_original_interrupt = bb622_bios_interrupt;\r\n',b'        bb_v15_original_interrupt = bb622_bios_interrupt;\n')),
    )
    for name, src in variants:
        with tempfile.TemporaryDirectory(prefix='bb622_textio_psram_') as d:
            root = Path(d)
            parent.fixture(root, src)
            parent.apply(root, original_inc)
            parent.verify(root, quiet=True)
            before = {p:(root/p).read_bytes() for p in (SRC, INC, *PARENTS)}
            modifications = plan(root, new_inc)
            assert len(modifications) == 2 + len(PARENTS)
            assert modifications[INC][1] == new_inc
            apply(root, new_inc)
            assert (root/SRC).read_bytes().count(b'bb622_textio_reset();') == 1
            assert (root/INC).read_bytes() == new_inc
            verify(root, quiet=True)
            restore(root)
            assert all((root/p).read_bytes() == data for p,data in before.items())
            assert not (root/STATE).exists()
            parent.verify(root, quiet=True)
            parent.restore(root)
            assert not (root/parent.STATE).exists()
            print(f'SELFTEST {name}: all manifest hashes + full install/verify/rollback PASS')
    print('SELFTEST PASS (4 source newline layouts; exact source and manifest restoration)')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root', type=Path, default=HERE)
    args = p.parse_args()
    root = args.root.resolve()
    try:
        new_inc = (HERE/'bb_dos622_textio.inc').read_bytes()
        if args.command == 'selftest': selftest(new_inc)
        elif args.command == 'probe':
            for k, (old,new) in plan(root,new_inc).items():
                print(f'{k}: {len(old)} -> {len(new)} bytes SHA {sha(old)[:12]} -> {sha(new)[:12]}')
            print('PROBE PASS (no changes made)')
        elif args.command == 'apply': apply(root, new_inc)
        elif args.command == 'verify': verify(root)
        elif args.command == 'restore': restore(root)
    except Exception as e:
        print(f'ERROR: {e}')
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
