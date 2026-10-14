#!/usr/bin/env python3
"""DOS 6.22 emergency SRAM headroom recovery. Complete reversible installer.

Does not alter JIT cache (232 KiB), disk drivers, CPU interpretation, DOS2,
RTC or screen behavior. Moves the sixteen remaining 512-byte tracking bitmaps
into Pico PSRAM, preserving the existing byte-exact tracking algorithm.

Commands: selftest, probe, apply, verify, restore
Requires all prior installer scripts/manifest state in C:\\blitzBUS.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
import bb_dos622_textio_psram_v1 as parent

HERE = Path(__file__).resolve().parent
TAG = 'BB_DOS622_SRAM_FLOOR_V1'
STATE = '.bb_dos622_sram_floor_v1_state'
SRC = parent.SRC
PARENTS = (*parent.PARENTS, parent.STATE + '/manifest.json')


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def jd(d: dict) -> bytes:
    return json.dumps(d, indent=2).encode('utf-8')


def between_once(src: bytes, begin: bytes, after: bytes, label: str, replace: bytes) -> bytes:
    if src.count(begin) != 1 or src.count(after) != 1:
        raise ValueError(f'{label}: expected one start/end anchor; got {src.count(begin)}/{src.count(after)}')
    b = src.index(begin)
    e = src.index(after, b)
    return src[:b] + replace + src[e:]


def transform(src: bytes) -> bytes:
    if TAG.encode('ascii') in src:
        raise ValueError('SRAM-floor stage already present; use verify')
    marker = b'/* BB_DOS622_HEAP_RESCUE_V1: reclaim core SRAM for the JIT calloc heap.'
    after = b'static unsigned trpool_used;'
    if src.count(b'BB_TR_HOT_PAGES') < 2 or src.count(b'trpool_cold') < 2:
        raise ValueError('heap-rescue v1 source layout missing; refusing to change')
    idx = src.index(marker) if marker in src else -1
    if idx < 0: raise ValueError('heap rescue marker absent')
    # Follow the actual newline at the marker. Never reserialize the whole C file.
    nl = b'\r\n' if b'\r\n' in src[idx:idx+140] else b'\n'
    block = '''/* BB_DOS622_HEAP_RESCUE_V1; BB_DOS622_SRAM_FLOOR_V1.
 * All translated-byte bitmaps live in PSRAM for DOS622 bring-up.
 * Each bitmap is explicitly zeroed when first assigned, as before.
 * BB_TR_HOT_PAGES can later be raised for a measured performance build.
 * No changes to BB_CODE_BYTES, JIT engine, or CPU instruction semantics. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#ifndef BB_TR_HOT_PAGES
#define BB_TR_HOT_PAGES 0u
#endif
#if BB_TR_HOT_PAGES > BB_TR_PAGES
#error "BB_TR_HOT_PAGES exceeds BB_TR_PAGES"
#endif
#if BB_TR_HOT_PAGES > 0u
static uint8_t trpool[BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
#if BB_TR_PAGES > BB_TR_HOT_PAGES
static uint8_t __uninitialized_psram("bb_trpool_cold")
    trpool_cold[BB_TR_PAGES - BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
#else
static uint8_t trpool[BB_TR_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
'''.encode('ascii').replace(b'\n', nl)
    src = between_once(src, marker, after, 'translated bitmap declaration', block)
    begin = b'#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && (BB_TR_PAGES > 16u)'
    end = b'                ++trpool_used;'
    use = '''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#if BB_TR_HOT_PAGES > 0u && BB_TR_PAGES > BB_TR_HOT_PAGES
                trbits[p] = trpool_used < BB_TR_HOT_PAGES ? trpool[trpool_used]
                            : trpool_cold[trpool_used - BB_TR_HOT_PAGES];
#elif BB_TR_HOT_PAGES > 0u
                trbits[p] = trpool[trpool_used];
#else
                trbits[p] = trpool_cold[trpool_used];
#endif
#else
                trbits[p] = trpool[trpool_used];
#endif
'''.encode('ascii').replace(b'\n', nl)
    src = between_once(src, begin, end, 'translated bitmap assignment', use)
    if src.count(TAG.encode()) != 1 or src.count(b'++trpool_used;') != 1:
        raise ValueError('post-transform anchor validation failed')
    return src


def plan(root: Path):
    if (root / STATE).exists():
        raise ValueError(f'{STATE} exists: already installed; use verify/restore')
    parent.verify(root, quiet=True)
    old = {p: (root / p).read_bytes() for p in (SRC, *PARENTS)}
    changed = {SRC: transform(old[SRC])}
    for path in PARENTS:
        obj = copy.deepcopy(json.loads(old[path]))
        for tracked, entry in obj.get('files', {}).items():
            if tracked in changed:
                for key in ('installed', 'new', 'after'):
                    if key in entry: entry[key] = sha(changed[tracked])
        if path == parent.parent.rtc.DIAG:
            obj['parent_after'] = sha(changed[parent.parent.rtc.IPL])
        changed[path] = jd(obj)
    return {p: (old[p], changed[p]) for p in (SRC, *PARENTS)}


def verify(root: Path, quiet: bool = False):
    state = root / STATE
    meta = json.loads((state/'manifest.json').read_text(encoding='utf-8'))
    if meta.get('tag') != TAG: raise ValueError('unexpected SRAM-floor state tag')
    for path, ent in meta['files'].items():
        if sha((root/path).read_bytes()) != ent['after']:
            raise ValueError(f'installed file SHA mismatch: {path}')
        if sha((state/ent['backup']).read_bytes()) != ent['before']:
            raise ValueError(f'backup SHA mismatch: {path}')
    src = (root/SRC).read_bytes()
    if src.count(TAG.encode()) != 1 or b'#define BB_TR_HOT_PAGES 0u' not in src:
        raise ValueError('SRAM-floor source code absent')
    parent.verify(root, quiet=True)
    if not quiet: print('VERIFIED: all tracking bitmaps in PSRAM; original source/backups + nine parent SHA manifests')


def apply(root: Path):
    updates = plan(root)
    state = root / STATE
    state.mkdir()
    try:
        meta = {'tag': TAG, 'files': {}}
        for i, (path, (old, new)) in enumerate(updates.items()):
            backup = f'original_{i:02d}.bin'
            (state/backup).write_bytes(old)
            meta['files'][path] = {'before': sha(old), 'after': sha(new), 'backup': backup}
        (state/'manifest.json').write_bytes(jd(meta))
        for path, (old, new) in updates.items():
            target = root/path
            if target.read_bytes() != old:
                raise ValueError(f'file changed mid-install: {path}')
            target.write_bytes(new)
        verify(root, quiet=True)
    except BaseException:
        for path, (old, _) in updates.items():
            (root/path).write_bytes(old)
        shutil.rmtree(state, ignore_errors=True)
        raise
    print('APPLIED: remaining 8 KiB bitmaps moved SRAM -> PSRAM; 232 KiB JIT, RTC, DOS2, screen unchanged')


def restore(root: Path):
    verify(root, quiet=True)
    state = root/STATE
    m = json.loads((state/'manifest.json').read_text(encoding='utf8'))
    for path, ent in m['files'].items():
        (root/path).write_bytes((state/ent['backup']).read_bytes())
    shutil.rmtree(state)
    parent.verify(root, quiet=True)
    print('RESTORED: C source + all nine parent manifests exact bytes')


def selftest():
    # Full prior-stage fixtures, not just standalone regex samples.
    original_inc = (HERE/'bb_dos622_textio_v1_original.inc').read_bytes()
    psram_inc = (HERE/'bb_dos622_textio_psram_include.inc').read_bytes()
    heap_decl = '''/* BB_DOS622_HEAP_RESCUE_V1: reclaim core SRAM for the JIT calloc heap.
 * Keep the first 16 translated-page bitmaps in fast SRAM (DOS2 peaked at 15).
 * The remaining BB_TR_PAGES - 16 entries are in PSRAM; each is zeroed on use.
 * No changes to BB_CODE_BYTES, JIT entry code, or the CPU interpreter. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#define BB_TR_HOT_PAGES ((BB_TR_PAGES) > 16u ? 16u : (BB_TR_PAGES))
static uint8_t trpool[BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#if BB_TR_PAGES > BB_TR_HOT_PAGES
static uint8_t __uninitialized_psram("bb_trpool_cold")
    trpool_cold[BB_TR_PAGES - BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
#else
static uint8_t trpool[BB_TR_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
static unsigned trpool_used;
'''
    heap_use = '''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && (BB_TR_PAGES > 16u)
                trbits[p] = trpool_used < 16u ? trpool[trpool_used]
                            : trpool_cold[trpool_used - 16u];
#else
                trbits[p] = trpool[trpool_used];
#endif
                ++trpool_used;
'''
    base = ('''static void bb_v23_poll_input(void) {\n    if(!bb_video_seen||!R)return;\n    ++bb_v23_polls;\n}\nstatic int bb_v22_keyboard(void) {\n    bb_v23_poll_input();\n    return 1;\n}\n'''
        + heap_decl + '''void foo(unsigned p) {\n if (trpool_used < BB_TR_PAGES) {\n'''+heap_use+''' }\n}\n'''
        + '''static int start(MdRuntime *rt) {\n    if (bb_sd_dos622_active()) {\n        bb_v15_original_interrupt = bb622_bios_interrupt;\n    }\n    return 1;\n}\nB86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)\n{\n    if (R == NULL && !start(rt)) return 0;\n    bb_v23_poll_input();\n    return 1;\n}\n''').encode('ascii')
    for name, raw in (
        ('LF',base),('CRLF',base.replace(b'\n', b'\r\n')),
        ('MIXED',base.replace(b'                ++trpool_used;\n', b'                ++trpool_used;\r\n')),
        ('CRLF_LF',base.replace(b'\n', b'\r\n').replace(b'                ++trpool_used;\r\n', b'                ++trpool_used;\n'))):
        with tempfile.TemporaryDirectory(prefix='bb622_sram_floor_') as d:
            root = Path(d)
            parent.parent.fixture(root, raw)
            parent.parent.apply(root, original_inc)
            parent.apply(root, psram_inc)
            before = {p: (root/p).read_bytes() for p in (SRC,*PARENTS)}
            transformed = transform(before[SRC])
            assert transformed.count(TAG.encode()) == 1
            updates = plan(root)
            assert len(updates) == 1 + len(PARENTS)
            apply(root)
            verify(root, quiet=True)
            assert b'#define BB_TR_HOT_PAGES 0u' in (root/SRC).read_bytes()
            restore(root)
            assert all((root/p).read_bytes() == v for p,v in before.items())
            assert not (root/STATE).exists()
            parent.verify(root, quiet=True)
            print(f'SELFTEST {name}: real parent fixtures + install/verify/byte-exact restore PASS')
    print('SELFTEST PASS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root', type=Path, default=HERE)
    args = p.parse_args()
    root = args.root.resolve()
    try:
        if args.command == 'selftest': selftest()
        elif args.command == 'probe':
            x = plan(root)
            for path,(old,new) in x.items():
                print(f'{path}: {len(old)} -> {len(new)} bytes sha {sha(old)[:12]} -> {sha(new)[:12]}')
            print('PROBE PASS; no files modified; 8 KiB additional PSRAM tracking planned')
        elif args.command == 'apply': apply(root)
        elif args.command == 'verify': verify(root)
        elif args.command == 'restore': restore(root)
    except Exception as exc:
        print(f'ERROR: {exc}')
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
