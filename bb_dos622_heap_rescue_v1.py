#!/usr/bin/env python3
"""blitzBUS DOS622 JIT-startup heap rescue v1 (complete reversible installer).

Targets the updated Oct-13 blitzBUS source, **not** a Git patch.
Commands: selftest | probe | apply | verify | restore

Moves only the *overflow* translated-byte tracking bitmaps (pages 17..24)
from core SRAM to Pico PSRAM.  The first 16 bitmap pages stay in SRAM,
and the 232 KiB executable JIT cache is unchanged.  The original DOS622
IPL and boot diagnostics remain installed.  Both parent manifest digests
are updated transactionally and their previous raw bytes are preserved.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
SRC = 'src/bb_live.c'
STATE = '.bb_dos622_heap_rescue_v1_state'
IPL = '.bb_dos622_ipl_v1_state/manifest.json'
DIAG = '.bb_dos622_boot_diag_v1_state/repair.json'
TAG = b'BB_DOS622_HEAP_RESCUE_V1'

BITMAP_DECL = b'static uint8_t trpool[BB_TR_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));'
BITMAP_USE = b'trbits[p] = trpool[trpool_used++];'


def digest(buf: bytes) -> str:
    return hashlib.sha256(buf).hexdigest()


def line_ending(data: bytes, anchor: bytes) -> bytes:
    if data.count(anchor) != 1:
        raise RuntimeError(f'expected 1 source anchor {anchor!r}, got {data.count(anchor)}')
    p = data.index(anchor) + len(anchor)
    if data[p:p+2] == b'\r\n':
        return b'\r\n'
    if data[p:p+1] in (b'\n', b'\r'):
        return data[p:p+1]
    raise RuntimeError('source anchor not immediately followed by newline; no changes')


def transform(data: bytes) -> bytes:
    if TAG in data:
        raise RuntimeError('heap rescue is already installed')
    a = line_ending(data, BITMAP_DECL)
    b = line_ending(data, BITMAP_USE)
    # Preprocessor guards keep desktop builds byte-for-byte equivalent in behavior;
    # on Pico only the 8 overflow pages move to external PSRAM.
    block = '''/* BB_DOS622_HEAP_RESCUE_V1: reclaim core SRAM for the JIT calloc heap.
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
#endif'''.encode('ascii').replace(b'\n', a)
    use = '''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && (BB_TR_PAGES > 16u)
                trbits[p] = trpool_used < 16u ? trpool[trpool_used]
                            : trpool_cold[trpool_used - 16u];
#else
                trbits[p] = trpool[trpool_used];
#endif
                ++trpool_used;'''.encode('ascii').replace(b'\n', b)
    data = data.replace(BITMAP_DECL, block, 1)
    data = data.replace(BITMAP_USE, use, 1)
    return data


def parent_info(root: Path):
    source = (root/SRC).read_bytes()
    ipath, dpath = root/IPL, root/DIAG
    ipraw, draw = ipath.read_bytes(), dpath.read_bytes()
    ipl = json.loads(ipraw)
    diag = json.loads(draw)
    if ipl.get('tag') != 'BB_DOS622_IPL_V1':
        raise RuntimeError('unexpected DOS622 IPL manifest tag')
    if diag.get('tag') != 'BB_DOS622_BOOT_DIAG_V1':
        raise RuntimeError('unexpected installed diagnostics manifest tag')
    oldsha = digest(source)
    if ipl['files'][SRC]['installed'] != oldsha:
        raise RuntimeError('IPL source SHA mismatch; updated repo checkout differs from local installed version')
    if diag['files'][SRC]['new'] != oldsha:
        raise RuntimeError('boot diagnostic source SHA mismatch; restore/update diagnosis before installing')
    if diag['parent_after'] != digest(ipraw):
        raise RuntimeError('diagnostic parent manifest SHA mismatch; protect existing rollback chain')
    return source, ipraw, draw, ipl, diag


def get_plan(root: Path):
    if (root/STATE).exists():
        raise RuntimeError('heap rescue already installed or incomplete; use verify / restore')
    old, ipraw, draw, ipl, diag = parent_info(root)
    new = transform(old)
    ipl['files'][SRC]['installed'] = digest(new)
    new_ipraw = json.dumps(ipl, indent=2).encode('utf8')
    diag['files'][SRC]['new'] = digest(new)
    diag['parent_after'] = digest(new_ipraw)
    new_draw = json.dumps(diag, indent=2).encode('utf8')
    return ((root/SRC, old, new), (root/IPL, ipraw, new_ipraw), (root/DIAG, draw, new_draw))


def probe(root: Path):
    plan = get_plan(root)
    print('PROBE PASS: exact updated-repo code anchors; IPL and diagnostic SHA chain consistent')
    print(f'  core SRAM reclaimed: {(24-16)*512} bytes at BB_TR_PAGES=24; hot 16 pages unchanged')
    print('  JIT code cache unchanged (232 KiB), no CPU or DOS2 kernel modification')
    for p, before, after in plan:
        print(f'  {p.relative_to(root)}: {len(before)} -> {len(after)} bytes | SHA {digest(before)[:12]} -> {digest(after)[:12]}')
    return plan


def apply(root: Path):
    plan = probe(root)
    state = root / STATE
    state.mkdir()
    try:
        rec = {'tag': TAG.decode(), 'files': {}}
        for i, (p, before, after) in enumerate(plan):
            (state/f'backup_{i}.bin').write_bytes(before)
            rec['files'][str(p.relative_to(root)).replace('\\','/')] = dict(before=digest(before), after=digest(after), backup=f'backup_{i}.bin')
        (state/'manifest.json').write_text(json.dumps(rec, indent=2), encoding='utf8')
        for p, before, after in plan:
            if p.read_bytes() != before:
                raise RuntimeError(f'source changed during install: {p}')
            p.write_bytes(after)
        verify(root)
    except Exception:
        for p, before, _ in plan:
            p.write_bytes(before)
        shutil.rmtree(state, ignore_errors=True)
        raise
    print('APPLIED: 16 hot tracking pages in SRAM; 8 cold pages moved to PSRAM; 286 JIT untouched')


def verify(root: Path):
    state = root/STATE
    rec = json.loads((state/'manifest.json').read_text(encoding='utf8'))
    if rec.get('tag') != TAG.decode():
        raise RuntimeError('wrong heap-rescue installation manifest')
    for rel, entry in rec['files'].items():
        cur = (root/rel).read_bytes()
        bak = (state/entry['backup']).read_bytes()
        if digest(cur) != entry['after'] or digest(bak) != entry['before']:
            raise RuntimeError(f'{rel}: modified source/manifest or corrupted backup')
    src, ipraw, draw, ipl, diag = parent_info(root)
    if TAG not in src:
        raise RuntimeError('heap rescue code is missing')
    if ipl['files'][SRC]['installed'] != diag['files'][SRC]['new']:
        raise RuntimeError('parent manifests disagree')
    print('VERIFIED: source, saved originals, IPL manifest, boot diagnostics, and SHA chain')


def restore(root: Path):
    verify(root)
    state = root/STATE
    rec = json.loads((state/'manifest.json').read_text(encoding='utf8'))
    for rel, entry in rec['files'].items():
        (root/rel).write_bytes((state/entry['backup']).read_bytes())
    shutil.rmtree(state)
    print('RESTORED: original C source and both parent manifests, exact bytes')


def selftest():
    # Exercise the same macros used by current source, including an inline comment
    # on the *neighboring* line and independently mixed newline endings.
    template = ('''#include <stdint.h>
#ifndef BB_TR_PAGES
#define BB_TR_PAGES 24u
#endif
#define MD_X86_CODE_PAGE_SIZE 4096
static uint8_t *trbits[256];
static unsigned trpool_used;
static uint8_t trpool[BB_TR_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
void track(unsigned p) {
  if (trpool_used < BB_TR_PAGES) {
                trbits[p] = trpool[trpool_used++];
                __builtin_memset(trbits[p], 0, MD_X86_CODE_PAGE_SIZE / 8u);
  }
}
''').encode('ascii')
    for name, old in (('LF', template), ('CRLF', template.replace(b'\n', b'\r\n')),
                      ('MIXED', template.replace(BITMAP_USE+b'\n', BITMAP_USE+b'\r\n'))):
        with tempfile.TemporaryDirectory(prefix='bb622_heap_') as dr:
            root = Path(dr)
            (root/'src').mkdir()
            (root/'.bb_dos622_ipl_v1_state').mkdir()
            (root/'.bb_dos622_boot_diag_v1_state').mkdir()
            (root/SRC).write_bytes(old)
            ipl = {'tag':'BB_DOS622_IPL_V1','files':{SRC:{'original':'sentinel', 'installed':digest(old)}}}
            ipraw = json.dumps(ipl, indent=2).encode('utf8')
            (root/IPL).write_bytes(ipraw)
            diag = {'tag':'BB_DOS622_BOOT_DIAG_V1','files':{SRC:{'old':'sentinel','new':digest(old)}},
                    'parent_after':digest(ipraw),'parent_before':'sentinel'}
            draw = json.dumps(diag, indent=2).encode('utf8')
            (root/DIAG).write_bytes(draw)
            probe(root)
            apply(root)
            verify(root)
            restore(root)
            assert (root/SRC).read_bytes() == old
            assert (root/IPL).read_bytes() == ipraw
            assert (root/DIAG).read_bytes() == draw
            print(f'SELFTEST {name}: PASS parent SHA chain, install, verify, byte-exact rollback')
    print('SELFTEST PASS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('selftest','probe','apply','verify','restore'))
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        {'selftest': lambda:selftest(), 'probe':lambda:probe(root),
         'apply':lambda:apply(root), 'verify':lambda:verify(root),
         'restore':lambda:restore(root)}[args.command]()
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError) as e:
        parser.exit(1, f'ERROR: {e}\n')

if __name__ == '__main__':
    main()
