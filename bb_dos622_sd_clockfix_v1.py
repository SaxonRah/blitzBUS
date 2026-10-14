#!/usr/bin/env python3
"""Repair the DOS622.IMG post-LCD SD SPI1 clock and retain IPL-v1 verification.

Install this COMPLETE script and bb_dos622_sd.inc in C:\\blitzBUS.
Actions: selftest | probe | apply | verify | restore. Does not use Git patches.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
REL = 'sd_boot/bb_dos622_sd.inc'
PARENT = '.bb_dos622_ipl_v1_state'
STATE = '.bb_dos622_sd_clockfix_v1_state'
ORIGINAL_SHA_LF = '0059624ebf7b66d65e8575004f608cfcb5e3784c145cf8fc5a3f539886d11466'
MARKER = b'BB_DOS622_CLOCKFIX_V1'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parent_info(root: Path) -> tuple[Path, bytes, dict]:
    p = root / PARENT / 'manifest.json'
    if not p.is_file():
        raise ValueError(f'IPL-v1 manifest not found: {p}; run the IPL installer first')
    raw = p.read_bytes()
    obj = json.loads(raw.decode('utf-8'))
    if obj.get('tag') != 'BB_DOS622_IPL_V1':
        raise ValueError('IPL-v1 manifest has unexpected tag')
    entry = obj.get('files', {}).get(REL)
    if not isinstance(entry, dict) or entry.get('original') is not None:
        raise ValueError(f'IPL-v1 manifest lacks expected created-file entry for {REL}')
    return p, raw, obj


def expected_fix(root: Path, orig: bytes) -> bytes:
    if MARKER in orig:
        raise ValueError('Source already contains clock fix; use verify')
    if sha(orig.replace(b'\r\n', b'\n')) != ORIGINAL_SHA_LF:
        raise ValueError('Installed DOS622 SD source differs from original IPL v1; refusing to replace custom code')
    src = root / 'bb_dos622_sd.inc'
    if not src.is_file():
        raise ValueError('Extract the full replacement bb_dos622_sd.inc next to this installer')
    new = src.read_bytes()
    if new.count(MARKER) != 1 or new.count(b'bb622_retime_spi1();') != 1:
        raise ValueError('Replacement SD source is missing expected clock-fix anchors')
    if orig.count(b'\r\n') and orig.count(b'\n') == orig.count(b'\r\n'):
        new = new.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    return new


def probe(root: Path = ROOT, quiet: bool = False) -> tuple[bytes, bytes, bytes, bytes]:
    if (root / STATE).exists():
        raise ValueError('Clockfix installation state already exists; use verify or restore')
    target = root / REL
    if not target.is_file():
        raise ValueError(f'Missing installed source: {target}')
    original = target.read_bytes()
    new = expected_fix(root, original)
    parent_path, old_parent, obj = parent_info(root)
    if obj['files'][REL].get('installed') != sha(original):
        raise ValueError('IPL-v1 manifest hash disagrees with original DOS622 source; do not alter it')
    obj['files'][REL]['installed'] = sha(new)
    new_parent = json.dumps(obj, indent=2).encode('utf-8')
    if not quiet:
        print(f'SD source: {len(original)} -> {len(new)} bytes; SHA-256 original validated')
        print(f'IPL-v1 parent manifest: {parent_path}; created-file SHA will be updated')
        print('PROBE PASS - source, DOS2 kernel, JIT, and cache unchanged')
    return original, new, old_parent, new_parent


def apply(root: Path = ROOT) -> None:
    old, new, old_parent, new_parent = probe(root)
    state = root / STATE
    target = root / REL
    parent_path = root / PARENT / 'manifest.json'
    state.mkdir()
    try:
        (state / 'original_sd.inc').write_bytes(old)
        (state / 'original_ipl_manifest.json').write_bytes(old_parent)
        (state / 'repair.json').write_text(json.dumps({
            'version': 1,
            'sd_before': sha(old), 'sd_after': sha(new),
            'manifest_before': sha(old_parent), 'manifest_after': sha(new_parent),
        }, indent=2), encoding='utf-8')
        target.write_bytes(new)
        parent_path.write_bytes(new_parent)
        verify(root)
    except Exception:
        target.write_bytes(old)
        parent_path.write_bytes(old_parent)
        shutil.rmtree(state, ignore_errors=True)
        raise
    print('APPLIED: DOS622 SPI1 12.5MHz retiming before FatFs read; IPL-v1 verify retained')


def verify(root: Path = ROOT) -> None:
    state = root / STATE
    if not state.is_dir():
        raise ValueError('Clockfix state absent; apply first')
    meta = json.loads((state / 'repair.json').read_text(encoding='utf-8'))
    old = (state / 'original_sd.inc').read_bytes()
    old_manifest = (state / 'original_ipl_manifest.json').read_bytes()
    sd = (root / REL).read_bytes()
    parent_path, manifest, obj = parent_info(root)
    for label, actual, expected in [
        ('saved original C', sha(old), meta['sd_before']),
        ('fixed C', sha(sd), meta['sd_after']),
        ('saved original manifest', sha(old_manifest), meta['manifest_before']),
        ('updated manifest', sha(manifest), meta['manifest_after']),
    ]:
        if actual != expected:
            raise ValueError(f'{label}: SHA mismatch; no changes made')
    if obj['files'][REL].get('installed') != sha(sd) or MARKER not in sd:
        raise ValueError('IPL-v1 parent manifest and clockfix disagree')
    if sha(old.replace(b'\r\n', b'\n')) != ORIGINAL_SHA_LF:
        raise ValueError('Clockfix original backup does not match the known source')
    print('VERIFIED: SPI clockfix, IPL-v1 manifest, exact rollback backups all intact')


def restore(root: Path = ROOT) -> None:
    verify(root)
    state = root / STATE
    (root / REL).write_bytes((state / 'original_sd.inc').read_bytes())
    (root / PARENT / 'manifest.json').write_bytes((state / 'original_ipl_manifest.json').read_bytes())
    shutil.rmtree(state)
    print('RESTORED: original IPL-v1 SD source and manifest byte-for-byte')


def selftest() -> None:
    template = ROOT / 'bb_dos622_sd_original_v1.inc'
    if not template.is_file():
        raise ValueError('Selftest source bb_dos622_sd_original_v1.inc is missing')
    raw = template.read_bytes()
    if sha(raw) != ORIGINAL_SHA_LF:
        raise ValueError('Selftest original source SHA mismatch')
    for ending in ('LF', 'CRLF'):
        with tempfile.TemporaryDirectory(prefix='bb622_sdclk_') as temp:
            root = Path(temp)
            (root / 'sd_boot').mkdir()
            (root / PARENT).mkdir()
            orig = raw if ending == 'LF' else raw.replace(b'\n', b'\r\n')
            (root / REL).write_bytes(orig)
            (root / 'bb_dos622_sd.inc').write_bytes((ROOT / 'bb_dos622_sd.inc').read_bytes())
            manifest = {'tag': 'BB_DOS622_IPL_V1', 'files': {
                REL: {'original': None, 'installed': sha(orig)},
                'sd_boot/bb_sd_boot.c': {'original': 'preserved', 'installed': 'preserved'},
            }}
            (root / PARENT / 'manifest.json').write_bytes(json.dumps(manifest, indent=2).encode('utf-8'))
            old_manifest = (root / PARENT / 'manifest.json').read_bytes()
            probe(root, quiet=True)
            apply(root)
            verify(root)
            assert sha((root / REL).read_bytes()) == sha(expected_fix_for_test(root, orig))
            restore(root)
            assert (root / REL).read_bytes() == orig
            assert (root / PARENT / 'manifest.json').read_bytes() == old_manifest
            print(f'{ending}: exact source + IPL manifest restoration PASS')
    print('SELFTEST PASS: LF/CRLF, SHA guard, install, parent verify, exact-byte rollback')


def expected_fix_for_test(root: Path, orig: bytes) -> bytes:
    return expected_fix(root, orig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['selftest', 'probe', 'apply', 'verify', 'restore'])
    args = ap.parse_args()
    {'selftest': selftest, 'probe': probe, 'apply': apply,
     'verify': verify, 'restore': restore}[args.action]()


if __name__ == '__main__':
    try:
        main()
    except (OSError, AssertionError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(1)
