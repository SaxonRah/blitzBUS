#!/usr/bin/env python3
"""DOS 6.22 startup tracing with exact-byte rollback and IPL manifest preservation.

Full installer, not a Git patch. Usage:
    python bb_dos622_boot_diag_v1.py selftest|probe|apply|verify|restore

Instruments cold startup only. No alterations to native JIT/cache or SD transfer code.
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
STATE = '.bb_dos622_boot_diag_v1_state'
PARENT = '.bb_dos622_ipl_v1_state'
TAG = 'BB_DOS622_BOOT_DIAG_V1'
FILES = ('src/bb_live.c', 'src/bb_dos622_bios.inc')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(data: bytes, needle: bytes, replacement: bytes, where: str) -> bytes:
    count = data.count(needle)
    if count != 1:
        raise ValueError(f'{where}: expected exactly 1 instance of {needle[:92]!r}; found {count}')
    return data.replace(needle, replacement, 1)


def transform(name: str, data: bytes) -> bytes:
    """Insert diagnostics without assuming a file-wide newline style.

    bb_live.c can have mixed LF and CRLF because other reversible installers
    preserve/insert their own line endings. Match each anchor independently,
    reuse *that particular line's* newline, and leave all other bytes alone.
    """
    import re

    if TAG.encode('ascii') in data:
        raise ValueError(f'{name}: already installed; run verify')

    def trace(label: str, newline: bytes, indent: str = '    ') -> bytes:
        return (f'{indent}printf("[bb622-diag] {label}\\n"); fflush(stdout);').encode('ascii') + newline

    def insert_at_line(line: str, make_replacement) -> None:
        nonlocal data
        needle = line.encode('ascii')
        # Anchor a C statement, not its entire physical line: the actual
        # blitzBUS source has an inline explanatory comment after C.model.
        # Accept only whitespace or a trailing C comment, rejecting extra
        # statements and avoiding matches in commented-out code.
        suffix = rb'[ \t]*(?:(?:/\*[^\r\n]*\*/)|(?://[^\r\n]*))?[ \t]*'
        regex = re.compile(rb'(?m)^' + re.escape(needle) +
                           rb'(?P<suffix>' + suffix + rb')(?P<nl>\r\n|\n|\r|$)')
        hits = list(regex.finditer(data))
        if len(hits) != 1:
            # Show the real nearby source text if an upstream revision has
            # changed the statement or indentation. No source is modified.
            symbol = line.strip().split('(')[0].split('=')[0].strip().encode('ascii')
            nearby = [x[:180].decode('ascii', 'replace') for x in data.splitlines()
                      if symbol in x][:4]
            raise ValueError(f'{name}: expected one statement {line!r}; '
                             f'found {len(hits)}; matching source lines={nearby!r}')
        hit = hits[0]
        original = hit.group(0)
        nl = hit.group('nl') or b'\n'
        result = make_replacement(original, nl)
        data = data[:hit.start()] + result + data[hit.end():]

    if name == 'src/bb_live.c':
        # The opening brace can itself have a newline different from the
        # function signature. The inserted lines follow the brace's style.
        header = re.compile(rb'(?m)^static int start\(MdRuntime \*rt\)(?P<n1>\r\n|\n|\r)\{(?P<n2>\r\n|\n|\r)')
        matches = list(header.finditer(data))
        if len(matches) != 1:
            raise ValueError(f'{name}: expected exactly one start() opening; found {len(matches)}')
        match = matches[0]
        data = (data[:match.start()] + match.group(0) +
                b'    /* ' + TAG.encode('ascii') + b' */' + match.group('n2') +
                trace('01 start.enter', match.group('n2')) + data[match.end():])

        insert_at_line('    b86_init(&C, rt->cpu.memory);',
            lambda old, nl: trace('02 before.b86_init', nl) + old + trace('03 after.b86_init', nl))
        insert_at_line('    (void)bb386_test_run(rt->cpu.memory);',
            lambda old, nl: trace('04 before.386_probe', nl) + old + trace('05 after.386_probe', nl))
        insert_at_line('    C.model = BB_CPU_MODEL;',
            lambda old, nl: trace('06 before.cpu_model', nl) + old)
        insert_at_line('    J = b86_jit_create_ex(&C, bb_code, BB_CODE_BYTES, bb_hot, sizeof bb_hot);',
            lambda old, nl: trace('07 before.jit_create', nl) + old + trace('08 after.jit_create', nl))
        insert_at_line('    bb_v15_original_interrupt = rt->hooks.interrupt;',
            lambda old, nl: trace('09 before.bios_hook', nl) + old)
        insert_at_line('        if (!bb622_boot_floppy(rt)) {',
            lambda old, nl: trace('10 before.dos622_boot', nl, '        ') + old)

    elif name == 'src/bb_dos622_bios.inc':
        insert_at_line('    if (!bb_sd_dos622_active()) return false;',
            lambda old, nl: b'    /* ' + TAG.encode('ascii') + b' */' + nl +
                            trace('11 enter.boot_floppy', nl) + old)
        insert_at_line('    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) return false;',
            lambda old, nl:
                trace('12 before.sector0', nl) +
                b'    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) {' + nl +
                trace('13 sector0.FAILED', nl, '        ') +
                b'        return false;' + nl +
                b'    }' + nl + trace('14 sector0.OK', nl))
        insert_at_line('    md_runtime_load_raw(rt, bb622_sector, 512u, 0x0000u, 0x7C00u);',
            lambda old, nl: trace('15 before.copy_boot_sector', nl) + old +
                            trace('16 after.copy_boot_sector', nl))
    else:
        raise ValueError(f'Unknown target {name}')
    return data


def parent_manifest(root: Path):
    path = root / PARENT / 'manifest.json'
    if not path.is_file():
        raise ValueError(f'IPL manifest missing: {path}')
    raw = path.read_bytes()
    manifest = json.loads(raw.decode('utf8'))
    if manifest.get('tag') != 'BB_DOS622_IPL_V1':
        raise ValueError('Wrong parent manifest tag')
    for rel in FILES:
        if rel not in manifest.get('files', {}):
            raise ValueError(f'{rel}: missing in parent IPL manifest')
    return path, raw, manifest


def probe(root=ROOT, verbose=True):
    if (root / STATE).exists():
        raise ValueError('Diagnostic already installed; run verify or restore')
    _, raw_manifest, manifest = parent_manifest(root)
    outputs = {}
    for rel in FILES:
        old = (root / rel).read_bytes()
        if sha(old) != manifest['files'][rel]['installed']:
            raise ValueError(f'{rel}: original SHA differs from IPL parent manifest; aborting safely')
        new = transform(rel, old)
        outputs[rel] = (old, new)
        manifest['files'][rel]['installed'] = sha(new)
        if verbose:
            newline_style = 'CRLF' if b'\r\n' in old else 'LF'
            print(f'{rel}: {len(old)} -> {len(new)} bytes, {newline_style}, anchor PASS')
    new_manifest = json.dumps(manifest, indent=2).encode('utf8')
    if verbose:
        print('PROBE PASS — no files changed; IPL and clockfix backups preserved')
    return outputs, raw_manifest, new_manifest


def apply(root=ROOT):
    outputs, raw_manifest, new_manifest = probe(root)
    state = root / STATE
    state.mkdir()
    mpath = root / PARENT / 'manifest.json'
    try:
        record = {'tag': TAG, 'files': {}, 'parent_before': sha(raw_manifest),
                  'parent_after': sha(new_manifest)}
        (state / 'parent_before.json').write_bytes(raw_manifest)
        for rel, (before, after) in outputs.items():
            (state / (rel.replace('/', '__') + '.bak')).write_bytes(before)
            record['files'][rel] = {'old': sha(before), 'new': sha(after)}
        (state / 'repair.json').write_text(json.dumps(record, indent=2), encoding='utf8')
        for rel, (_, after) in outputs.items():
            (root / rel).write_bytes(after)
        mpath.write_bytes(new_manifest)
        verify(root)
    except Exception:
        for rel, (before, _) in outputs.items():
            (root / rel).write_bytes(before)
        mpath.write_bytes(raw_manifest)
        shutil.rmtree(state, ignore_errors=True)
        raise
    print('APPLIED — 16 flushed checkpoints (startup + DOS6 boot); 286 JIT and SD clockfix unchanged')


def verify(root=ROOT):
    state = root / STATE
    record = json.loads((state / 'repair.json').read_text(encoding='utf8'))
    if record.get('tag') != TAG:
        raise ValueError('Wrong state tag')
    parent_path, parent_raw, manifest = parent_manifest(root)
    if sha(parent_raw) != record['parent_after']:
        raise ValueError('IPL manifest modified after diagnostic installation')
    if sha((state / 'parent_before.json').read_bytes()) != record['parent_before']:
        raise ValueError('Saved IPL manifest corrupted')
    for rel, entry in record['files'].items():
        current = (root / rel).read_bytes()
        saved = (state / (rel.replace('/', '__') + '.bak')).read_bytes()
        if sha(current) != entry['new'] or sha(saved) != entry['old']:
            raise ValueError(f'{rel}: diagnostic or backup modified; no changes made')
        if manifest['files'][rel]['installed'] != entry['new']:
            raise ValueError(f'{rel}: parent manifest mismatch')
        if current.count(TAG.encode()) != 1:
            raise ValueError(f'{rel}: missing diagnostic tag')
    print('VERIFIED — trace source SHA, original backups, and IPL manifest intact')


def restore(root=ROOT):
    verify(root)
    state = root / STATE
    for rel in FILES:
        old = (state / (rel.replace('/', '__') + '.bak')).read_bytes()
        (root / rel).write_bytes(old)
    (root / PARENT / 'manifest.json').write_bytes((state / 'parent_before.json').read_bytes())
    shutil.rmtree(state)
    print('RESTORED — all source and parent IPL manifest bytes exactly original')


def selftest():
    for ending in ('LF', 'CRLF'):
        eol = b'\n' if ending == 'LF' else b'\r\n'
        with tempfile.TemporaryDirectory(prefix='bb622_trace_') as dirname:
            root = Path(dirname)
            (root / 'src').mkdir(parents=True)
            (root / PARENT).mkdir()
            samples = {
                FILES[0]: '''static int start(MdRuntime *rt)\n{\n    b86_init(&C, rt->cpu.memory);\n    (void)bb386_test_run(rt->cpu.memory);\n    C.model = BB_CPU_MODEL;\n    J = b86_jit_create_ex(&C, bb_code, BB_CODE_BYTES, bb_hot, sizeof bb_hot);\n    bb_v15_original_interrupt = rt->hooks.interrupt;\n        if (!bb622_boot_floppy(rt)) {\n''',
                FILES[1]: '''    if (!bb_sd_dos622_active()) return false;\n    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) return false;\n    md_runtime_load_raw(rt, bb622_sector, 512u, 0x0000u, 0x7C00u);\n''',
            }
            manifest = {'tag': 'BB_DOS622_IPL_V1', 'files': {}}
            before = {}
            for rel, data in samples.items():
                raw = data.encode().replace(b'\n', eol)
                (root / rel).write_bytes(raw)
                before[rel] = raw
                manifest['files'][rel] = {'original': None, 'installed': sha(raw)}
            (root / PARENT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
            pbytes = (root / PARENT / 'manifest.json').read_bytes()
            probe(root, verbose=False)
            apply(root)
            verify(root)
            restore(root)
            assert (root / PARENT / 'manifest.json').read_bytes() == pbytes
            for rel, raw in before.items():
                assert (root / rel).read_bytes() == raw, f'{rel} not byte-exact'
            print(f'SELFTEST {ending}: PASS exact install/verify/restore and parent manifest')
    # Regression: actual blitzBUS bb_live.c can be predominantly CRLF while
    # its C.model line retains LF (or vice versa) from layered installers.
    for mixed in ('CRLF_WITH_LF_MODEL', 'LF_WITH_CRLF_MODEL'):
        with tempfile.TemporaryDirectory(prefix='bb622_trace_mixed_') as dirname:
            root = Path(dirname)
            (root / 'src').mkdir(parents=True)
            (root / PARENT).mkdir()
            base_nl = b'\r\n' if mixed.startswith('CRLF') else b'\n'
            model_nl = b'\n' if base_nl == b'\r\n' else b'\r\n'
            live = ('''static int start(MdRuntime *rt)
{
    b86_init(&C, rt->cpu.memory);
    (void)bb386_test_run(rt->cpu.memory);
    C.model = BB_CPU_MODEL;
    J = b86_jit_create_ex(&C, bb_code, BB_CODE_BYTES, bb_hot, sizeof bb_hot);
    bb_v15_original_interrupt = rt->hooks.interrupt;
        if (!bb622_boot_floppy(rt)) {
''').encode('ascii').replace(b'\n', base_nl)
            live = live.replace(b'    C.model = BB_CPU_MODEL;' + base_nl,
                                b'    C.model = BB_CPU_MODEL;' + model_nl)
            bios = ('''    if (!bb_sd_dos622_active()) return false;
    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) return false;
    md_runtime_load_raw(rt, bb622_sector, 512u, 0x0000u, 0x7C00u);
''').encode('ascii').replace(b'\n', base_nl)
            bios = bios.replace(b'    md_runtime_load_raw(rt, bb622_sector, 512u, 0x0000u, 0x7C00u);' + base_nl,
                                b'    md_runtime_load_raw(rt, bb622_sector, 512u, 0x0000u, 0x7C00u);' + model_nl)
            raw_files = {FILES[0]: live, FILES[1]: bios}
            manifest = {'tag': 'BB_DOS622_IPL_V1', 'files': {}}
            for rel, raw in raw_files.items():
                (root / rel).write_bytes(raw)
                manifest['files'][rel] = {'original': None, 'installed': sha(raw)}
            (root / PARENT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
            saved_manifest = (root / PARENT / 'manifest.json').read_bytes()
            outputs, _, _ = probe(root, verbose=False)
            assert outputs[FILES[0]][1].count(b'    C.model = BB_CPU_MODEL;' + model_nl) == 1
            apply(root)
            verify(root)
            restore(root)
            assert (root / PARENT / 'manifest.json').read_bytes() == saved_manifest
            assert all((root / rel).read_bytes() == raw for rel, raw in raw_files.items())
            print(f'SELFTEST {mixed}: PASS all 16 anchors, manifest and byte-exact rollback')
    # Reproduction of the actual blitzBUS source line: the model assignment
    # has a trailing C comment, and older installers incorrectly demanded a
    # newline immediately after the semicolon. Test source-level punctuation.
    for variation in ('INLINE_MODEL_COMMENT', 'INLINE_COMMENTS_MIXED_EOL'):
        with tempfile.TemporaryDirectory(prefix='bb622_trace_real_') as dirname:
            root = Path(dirname)
            (root / 'src').mkdir(parents=True)
            (root / PARENT).mkdir()
            a = b'\r\n' if variation.endswith('MIXED_EOL') else b'\n'
            b = b'\n' if a == b'\r\n' else a
            live = (
                b'static int start(MdRuntime *rt)' + a +
                b'{' + a +
                b'    b86_init(&C, rt->cpu.memory);' + a +
                b'    (void)bb386_test_run(rt->cpu.memory);' + a +
                b'    C.model = BB_CPU_MODEL;            /* v63: 0 = 8086 (exact), 1 = 80186 instruction set */' + b +
                b'    J = b86_jit_create_ex(&C, bb_code, BB_CODE_BYTES, bb_hot, sizeof bb_hot);' + a +
                b'    bb_v15_original_interrupt = rt->hooks.interrupt;' + a +
                b'        if (!bb622_boot_floppy(rt)) {' + a
            )
            bios = (
                b'    if (!bb_sd_dos622_active()) return false;' + a +
                b'    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) return false;' + a +
                b'    md_runtime_load_raw(rt, bb622_sector, 512u, 0x0000u, 0x7C00u);' + a
            )
            raw_files = {FILES[0]: live, FILES[1]: bios}
            manifest = {'tag': 'BB_DOS622_IPL_V1', 'files': {}}
            for rel, raw in raw_files.items():
                (root / rel).write_bytes(raw)
                manifest['files'][rel] = {'original': None, 'installed': sha(raw)}
            mpath = root / PARENT / 'manifest.json'
            mpath.write_text(json.dumps(manifest, indent=2), encoding='utf8')
            original_manifest = mpath.read_bytes()
            outputs, _, _ = probe(root, verbose=False)
            modified = outputs[FILES[0]][1]
            assert b'C.model = BB_CPU_MODEL;            /* v63:' in modified
            assert b'[bb622-diag] 06 before.cpu_model\\n' in modified
            apply(root)
            verify(root)
            restore(root)
            assert mpath.read_bytes() == original_manifest
            assert all((root / rel).read_bytes() == raw for rel, raw in raw_files.items())
            print(f'SELFTEST {variation}: PASS trailing comment, manifest, byte-exact restore')
    print('SELFTEST PASS — LF/CRLF/MIXED/INLINE-COMMENTS, 16 anchors, parent SHA, byte-exact rollback')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['selftest','probe','apply','verify','restore'])
    args=p.parse_args()
    {'selftest':selftest,'probe':probe,'apply':apply,'verify':verify,'restore':restore}[args.action]()

if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, AssertionError, json.JSONDecodeError) as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
