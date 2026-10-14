#!/usr/bin/env python3
"""Fix PM0 Pico probe include ordering while preserving PM0 SHA manifest.

Extract this full script into C:\\blitzBUS then run:
  python .\\bb_386_pm0_include_fix1.py selftest
  python .\\bb_386_pm0_include_fix1.py probe
  python .\\bb_386_pm0_include_fix1.py apply
  python .\\bb_386_pm0_include_fix1.py verify
  python .\\bb_386_pm0_v1.py verify

To remove only this fix: python .\\bb_386_pm0_include_fix1.py restore
This NEVER runs the Pico flash tool, and does not modify RM0/RM1/RM2/RM3.
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

HERE = Path(__file__).resolve().parent
KEY = 'blitzBUS/src/bb_live.c'
TAG = 'BB_386_PM0_INCLUDE_FIX1'


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def endline(b: bytes) -> bytes:
    bare = b.replace(b'\r\n', b'')
    if b'\r' in bare or (b'\r\n' in b and b'\n' in bare):
        raise ValueError('mixed newline styles; refusing to change source')
    return b'\r\n' if b'\r\n' in b else b'\n'


def source_fix(original: bytes) -> bytes:
    eol = endline(original)
    def nl(s: str) -> bytes:
        return s.encode('utf-8').replace(b'\n', eol)

    old_block = nl('''/* BB_386_PM0_V1: optional 386 interpreter smoke, isolated from DOS. */
#ifndef BB386_PICO_PROBE
#define BB386_PICO_PROBE 1
#endif
#if BB386_PICO_PROBE
#include "bb_386_pico_probe.inc"
#endif
''')
    place = nl('''/* BB_386_PM0_V1: optional 386 interpreter smoke, isolated from DOS. */
#ifndef BB386_PICO_PROBE
#define BB386_PICO_PROBE 1
#endif
/* BB_386_PM0_INCLUDE_FIX1: SDK PSRAM macro and libc must be declared first. */
#if BB386_PICO_PROBE
#include "bb_386_pico_probe.inc"
#endif
''')
    target = nl('#ifndef BB_TR_PAGES')

    if original.count(old_block) != 1:
        raise ValueError(f'expected one old PM0 probe include, found {original.count(old_block)}')
    if original.count(target) != 1:
        raise ValueError(f'expected one BB_TR_PAGES anchor, found {original.count(target)}')
    if original.count(nl('#include "b86.h"')) != 1:
        raise ValueError('b86.h include anchor missing/non-unique')
    if original.count(nl('#include "pico/stdlib.h"')) != 1:
        raise ValueError('Pico SDK include anchor missing/non-unique')
    before = original.replace(old_block, b'', 1)
    result = before.replace(target, place + eol + target, 1)
    pos = result.index(nl('#include "bb_386_pico_probe.inc"'))
    assert result.index(nl('#include "pico/stdlib.h"')) < pos
    assert result.index(nl('#include <string.h>')) < pos
    assert result.index(nl('#include "b86.h"')) < pos
    assert result.index(target) > pos
    assert result.count(nl('#include "bb_386_pico_probe.inc"')) == 1
    return result


def paths(root: Path):
    root = root.resolve()
    target = root / 'src' / 'bb_live.c'
    pm0 = root / '.bb_386_pm0_v1_backup' / 'manifest.json'
    own = root / '.bb_386_pm0_include_fix1_backup'
    return target, pm0, own


def atomic(path: Path, data: bytes):
    tmp = path.with_name(path.name + '.pm0fix_tmp')
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def check_manifest(src: bytes, raw_manifest: bytes, *, old: bool):
    m = json.loads(raw_manifest)
    if m.get('tag') != 'BB_386_PM0_V1':
        raise ValueError('not the expected PM0 install manifest')
    entry = m['edited'][KEY]
    if old and digest(src) != entry['after']:
        raise ValueError('PM0 source hash does not match install manifest: source changed since PM0 apply')
    return m


def probe(root: Path):
    source, pm0, own = paths(root)
    if own.exists():
        raise ValueError('fix already installed or interrupted; use verify/restore or inspect backup')
    if not source.is_file() or not pm0.is_file():
        raise ValueError('PM0 source/manifest missing; PM0 must be installed before this fix')
    original = source.read_bytes()
    m = check_manifest(original, pm0.read_bytes(), old=True)
    if not (root / 'src' / 'bb_386_pico_probe.inc').is_file():
        raise ValueError('PM0 probe file missing')
    fixed = source_fix(original)
    print(f'PROBE PASS: {len(original)} -> {len(fixed)} bytes, EOL={endline(original)!r}; '
          'Pico SDK includes now precede the 386 probe; PM0 manifest will be updated')
    return original, fixed, m


def apply(root: Path):
    original, fixed, m = probe(root)
    source, pm0, own = paths(root)
    original_manifest = pm0.read_bytes()
    m['edited'][KEY]['after'] = digest(fixed)
    updated_manifest = (json.dumps(m, indent=2) + '\n').encode('utf-8')
    own.mkdir(parents=False, exist_ok=False)
    try:
        atomic(own / 'source_before.bin', original)
        atomic(own / 'pm0_manifest_before.bin', original_manifest)
        atomic(own / 'state.json', (json.dumps({
            'tag': TAG,
            'original_source': digest(original), 'fixed_source': digest(fixed),
            'original_manifest': digest(original_manifest),
            'fixed_manifest': digest(updated_manifest)
        }, indent=2) + '\n').encode())
        atomic(source, fixed)
        atomic(pm0, updated_manifest)
        verify(root)
    except Exception:
        atomic(source, original)
        atomic(pm0, original_manifest)
        shutil.rmtree(own)
        raise
    print('APPLIED: probe include moved after Pico SDK headers; PM0 SHA manifest updated; 286 JIT unchanged')


def verify(root: Path):
    source, pm0, own = paths(root)
    if not own.is_dir():
        raise ValueError('fix backup missing; not applied')
    state = json.loads((own / 'state.json').read_text())
    if state.get('tag') != TAG:
        raise ValueError('unexpected fix backup')
    pairs = [(source, 'fixed_source'), (pm0, 'fixed_manifest'),
             (own / 'source_before.bin', 'original_source'),
             (own / 'pm0_manifest_before.bin', 'original_manifest')]
    for path, key in pairs:
        if digest(path.read_bytes()) != state[key]:
            raise ValueError('SHA mismatch for ' + str(path))
    if source.read_bytes().count(b'#include "bb_386_pico_probe.inc"') != 1:
        raise ValueError('probe include not unique')
    m = json.loads(pm0.read_bytes())
    if m['edited'][KEY]['after'] != state['fixed_source']:
        raise ValueError('PM0 manifest does not match repaired source')
    print('VERIFIED: repaired include order, PM0 manifest, exact original backups')


def restore(root: Path):
    verify(root)
    source, pm0, own = paths(root)
    src = (own / 'source_before.bin').read_bytes()
    manifest = (own / 'pm0_manifest_before.bin').read_bytes()
    atomic(source, src)
    atomic(pm0, manifest)
    shutil.rmtree(own)
    print('RESTORED: PM0 original source and manifest byte-exactly; RM0-RM3 untouched')


def selftest():
    for eol in ('\n', '\r\n'):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, pm0, _ = paths(root)
            source.parent.mkdir(parents=True)
            pm0.parent.mkdir(parents=True)
            old = '''#include "b86.h"
/* BB_386_PM0_V1: optional 386 interpreter smoke, isolated from DOS. */
#ifndef BB386_PICO_PROBE
#define BB386_PICO_PROBE 1
#endif
#if BB386_PICO_PROBE
#include "bb_386_pico_probe.inc"
#endif
#include <string.h>
#include <stdio.h>
#if defined(PICO_ON_DEVICE)
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#else
#include <time.h>
#endif
#ifndef BB_TR_PAGES
#define BB_TR_PAGES 24u
#endif
'''.replace('\n',eol).encode('utf-8')
            source.write_bytes(old)
            (root / 'src' / 'bb_386_pico_probe.inc').write_text('/* probe */\n')
            pm0_json = json.dumps({'tag':'BB_386_PM0_V1','edited':{
                KEY:{'before':'baseline-hash','after':digest(old)}
            }}, indent=2).encode()
            pm0.write_bytes(pm0_json)
            probe(root)
            apply(root)
            verify(root)
            assert source.read_bytes() != old
            assert endline(source.read_bytes()) == eol.encode()
            restore(root)
            assert source.read_bytes() == old
            assert pm0.read_bytes() == pm0_json
    print('SELFTEST PASS: LF/CRLF, SHA manifests, source relocation, reversible byte-exact restore')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('selftest', 'probe', 'apply', 'verify', 'restore'))
    ap.add_argument('--root', type=Path, default=Path(r'C:\blitzBUS'))
    args = ap.parse_args()
    if args.action == 'selftest':
        selftest()
    else:
        {'probe':probe, 'apply':apply, 'verify':verify, 'restore':restore}[args.action](args.root)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, AssertionError, json.JSONDecodeError) as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
