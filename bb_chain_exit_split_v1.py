#!/usr/bin/env python3
"""blitz86 native dispatcher exit-reason diagnostic, reversible full-file edit.

Copy to C:\\blitzBUS\\bb_chain_exit_split_v1.py and run:
  python bb_chain_exit_split_v1.py apply
  python bb_chain_exit_split_v1.py verify
  python bb_chain_exit_split_v1.py restore

Compatible with existing PSRAM layout, hot threshold, eviction and chain diagnostics.
This adds distinct return reasons for shared Thumb-2 exits, not a new lookup.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BLITZ = Path(r"C:\blitz86_v2") if sys.platform == 'win32' else ROOT / '__blitz86_fixture'
FILES = {
    'backend': BLITZ / 'src' / 'backend.h',
    'thumb': BLITZ / 'src' / 'be_t2.c',
    'jit': BLITZ / 'src' / 'jit.c',
    'public': BLITZ / 'include' / 'b86.h',
    'live': ROOT / 'src' / 'bb_live.c',
}
MANIFEST = ROOT / 'bb_chain_exit_split_v1_manifest.json'
MARKER = 'BB_CHAIN_EXIT_SPLIT_V1'

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def replace_once(text: str, anchor: str, replacement: str, label: str) -> str:
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f'{label}: expected one anchor, found {count}; no files changed')
    return text.replace(anchor, replacement, 1)

def transform(name: str, content: str) -> str:
    if name == 'backend':
        old = 'enum { XR_LOOKUP = 0, XR_CHAIN = 1, XR_HALT = 2, XR_IRQ = 3, XR_RETFILL = 4 };'
        new = '''/* BB_CHAIN_EXIT_SPLIT_V1: distinguish shared Thumb-2 exit paths. */
enum { XR_LOOKUP = 0, XR_CHAIN = 1, XR_HALT = 2, XR_IRQ = 3, XR_RETFILL = 4,
       XR_DYNAMIC = 5, XR_FASTMISS = 6 };'''
        return replace_once(content, old, new, name)
    if name == 'thumb':
        old = '''    e->x_dynexit = e->p;
    movw(e, R12, XR_LOOKUP);
    emit_b(e, e->x_epilogue);
    e->x_miss = e->x_dynexit;                        /* lookup stores ip first */'''
        new = '''    /* BB_CHAIN_EXIT_SPLIT_V1: both exits keep the same CPU state and epilogue. */
    e->x_dynexit = e->p;
    movw(e, R12, XR_DYNAMIC);
    emit_b(e, e->x_epilogue);
    e->x_miss = e->p;                                /* native SRAM fast lookup miss */
    movw(e, R12, XR_FASTMISS);
    emit_b(e, e->x_epilogue);'''
        return replace_once(content, old, new, name)
    if name == 'jit':
        old = '''        switch (r) {
        case XR_HALT: return B86_HALT;
        case XR_CHAIN:'''
        new = '''        switch (r) {
        case XR_HALT: return B86_HALT;
        /* BB_CHAIN_EXIT_SPLIT_V1: counters only; normal dispatcher behavior retained. */
        case XR_DYNAMIC: j->st.exit_dynamic++; break;
        case XR_FASTMISS: j->st.exit_native_miss++; break;
        case XR_LOOKUP: j->st.exit_direct_lookup++; break;
        case XR_CHAIN:'''
        return replace_once(content, old, new, name)
    if name == 'public':
        old = '''    uint64_t dispatches;
    uint64_t translate_us;'''
        new = '''    uint64_t dispatches;
    /* BB_CHAIN_EXIT_SPLIT_V1: shared native exit reason counts (cumulative). */
    uint64_t exit_dynamic, exit_native_miss, exit_direct_lookup;
    uint64_t translate_us;'''
        return replace_once(content, old, new, name)
    if name == 'live':
        old = '    printf("[bb-jit] native-ms='
        new = '''    /* BB_CHAIN_EXIT_SPLIT_V1: cumulative counters, distinct from delta bb-jit output. */
    printf("[bb-exit-split] dynamic=%llu native-fast-miss=%llu direct-lookup=%llu total-classified=%llu\\n",
           (unsigned long long)s->exit_dynamic,
           (unsigned long long)s->exit_native_miss,
           (unsigned long long)s->exit_direct_lookup,
           (unsigned long long)(s->exit_dynamic + s->exit_native_miss + s->exit_direct_lookup));
''' + old
        return replace_once(content, old, new, name)
    raise RuntimeError(name)

def apply() -> None:
    if MANIFEST.exists():
        print('Existing experiment manifest:', MANIFEST)
        verify()
        return
    old: dict[str, bytes] = {}
    new: dict[str, bytes] = {}
    for name, path in FILES.items():
        if not path.is_file():
            raise RuntimeError(f'Missing source: {path}')
        orig = path.read_bytes()
        if MARKER.encode() in orig:
            raise RuntimeError(f'File has marker but no manifest: {path}; inspect manually')
        # latin-1 guarantees preservation of all source bytes, including CRLF.
        original = orig.decode('latin-1')
        changed = transform(name, original)
        if changed == original:
            raise RuntimeError(f'No change made: {path}')
        old[name] = orig
        new[name] = changed.encode('latin-1')
    backups: dict[str, dict[str, str]] = {}
    for name, path in FILES.items():
        backup = path.with_name(path.name + '.chain-exit-split-v1.bak')
        if backup.exists():
            raise RuntimeError(f'Backup already exists: {backup}; refusing overwrite')
        backups[name] = dict(file=str(path),backup=str(backup),original_sha=sha(old[name]),modified_sha=sha(new[name]))
    for name, paths in backups.items():
        Path(paths['backup']).write_bytes(old[name])
    # All anchors and backups validated before making source changes.
    for name, path in FILES.items():
        path.write_bytes(new[name])
    MANIFEST.write_text(json.dumps(dict(marker=MARKER,files=backups),indent=2),encoding='utf-8')
    print('Installed exit-reason diagnostics. Existing memory layout and JIT policy unchanged.')
    print('Full-file backups and manifest:', MANIFEST)
    verify()

def verify() -> None:
    if not MANIFEST.is_file():
        raise RuntimeError('Manifest not found; run apply first')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest.get('marker') != MARKER:
        raise RuntimeError('Unexpected manifest marker')
    for name, item in manifest['files'].items():
        path = Path(item['file'])
        if not path.is_file() or sha(path.read_bytes()) != item['modified_sha']:
            raise RuntimeError(f'{name} modified after experiment was installed; manual reconciliation required: {path}')
        if not Path(item['backup']).is_file() or sha(Path(item['backup']).read_bytes()) != item['original_sha']:
            raise RuntimeError(f'{name} backup mismatch; cannot safely restore')
        print(name, 'OK', path)
    print('Source edits verified; firmware compilation and hardware behavior not yet tested.')

def restore() -> None:
    verify()  # Refuse to overwrite user changes made after apply.
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    for name, item in manifest['files'].items():
        Path(item['file']).write_bytes(Path(item['backup']).read_bytes())
        print('Restored', name)
    for item in manifest['files'].values():
        Path(item['backup']).unlink()
    MANIFEST.unlink()
    print('Restored all original source files. Rebuild/flash to apply.')

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command',choices=['apply','verify','restore'])
    a=parser.parse_args()
    try:
        {'apply':apply,'verify':verify,'restore':restore}[a.command]()
    except Exception as exc:
        print('ERROR:',exc,file=sys.stderr)
        sys.exit(1)

if __name__=='__main__':
    main()
