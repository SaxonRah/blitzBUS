#!/usr/bin/env python3
"""Fix RP2350 SRAM link overflow after blitz86 386 RM2, without shrinking JIT cache.

Move 386-only helpers and cold 286 opcode handlers into executable XIP flash,
keeping b86_step_internal(), native Thumb-2 backend, and 232 KiB JIT cache intact.

Apply on TOP of RM0, RM1, RM2, eager-unchaining, RCL/RCR work.

    cd C:\\blitzBUS
    python bb_386_rm2_v1.py verify
    python bb_386_rm2_flash_sram_v1.py selftest
    python bb_386_rm2_flash_sram_v1.py probe
    python bb_386_rm2_flash_sram_v1.py apply
    python bb_386_rm2_flash_sram_v1.py verify

Restore in reverse order (this fix BEFORE RM2):
    python bb_386_rm2_flash_sram_v1.py restore
    python bb_386_rm2_v1.py verify

RM2's old 'verify' is EXPECTED to detect changed SHA while this layer is on.
Never use RM2 'restore' until this layer has been restored first.
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

TAG = 'BB_386_RM2_FLASH_SRAM_V1'
HOME = Path(__file__).resolve().parent
BACK = HOME / '.bb_386_rm2_flash_sram_v1_backup'
FILES = ['src/interp.c', 'src/i386_rm0.inc', 'src/i386_rm1.inc', 'src/i386_rm2.inc']
# Explicit GCC/Clang section overrides .time_critical placement; noinline is
# needed because 'B86_COLD' in this project has NO noinline annotation.
ATTR = '__attribute__((noinline, cold, section(".text.bb386_flash")))'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def eol_of(raw: bytes) -> str:
    norm = raw.replace(b'\r\n', b'')
    if b'\r' in norm:
        raise RuntimeError('Mixed or unsupported CR line endings')
    return '\r\n' if b'\r\n' in raw else '\n'


def one(src: str, needle: str, replacement: str, label: str) -> str:
    found = src.count(needle)
    if found != 1:
        raise RuntimeError(f'{label}: expected one source anchor; found {found}. No files changed.')
    return src.replace(needle, replacement, 1)


def edit(relative: str, raw: bytes) -> bytes:
    nl = eol_of(raw)
    src = raw.decode('utf-8').replace('\r\n', '\n')
    if TAG in src:
        raise RuntimeError('Fix already installed; use verify')

    if relative.endswith('.inc'):
        expected = {'src/i386_rm0.inc': 9,
                    'src/i386_rm1.inc': 11,
                    'src/i386_rm2.inc': 6}[relative]
        count = src.count('B86_COLD static ')
        if count != expected:
            raise RuntimeError(f'{relative}: expected {expected} RM helper definitions; found {count}')
        src = src.replace('B86_COLD static ', f'static {ATTR} ')
        src = f'/* {TAG}: force every 386-only handler to XIP flash. */\n' + src
    elif relative == 'src/interp.c':
        for guard in ['BB_386_RM0_V1', 'BB_386_RM1_V1', 'BB_386_RM2_V1',
                      '#include "i386_rm2.inc"']:
            if guard not in src:
                raise RuntimeError(f'interp.c is missing {guard}: RM0/RM1/RM2 not installed')
        # The 386-only half of the B86_HOT b86_step wrapper must not live in
        # .time_critical; leave only the single model check in SRAM.
        a = 'B86_HOT int b86_step(B86Cpu *c)\n{\n    if (c->model < B86_CPU_386) return b86_step_internal(c);\n'
        b = '    return rc;\n}\n'
        if src.count(a) != 1:
            raise RuntimeError('386 b86_step wrapper not found exactly once')
        start = src.index(a)
        stop = src.find(b, start + len(a))
        if stop < 0:
            raise RuntimeError('386 b86_step wrapper closing anchor not found')
        stop += len(b)
        slow = src[start + len(a):stop - len(b)]
        if slow.count('uint32_t hi[8];') != 1 or 'b86_step_internal(c)' not in slow:
            raise RuntimeError('Unexpected changed 386 wrapper, refusing conversion')
        flash = (f'/* {TAG}: 386-only upper-register preservation in XIP flash. */\n'
                 f'static {ATTR} int b86_386_step_flash(B86Cpu *c)\n{{\n'
                 + slow + b
                 + '\nB86_HOT int b86_step(B86Cpu *c)\n{\n'
                   '    if (c->model < B86_CPU_386) return b86_step_internal(c);\n'
                   '    return b86_386_step_flash(c);\n}\n')
        src = src[:start] + flash + src[stop:]

        # These opcode families are infrequent, never on the 3DBench hot JIT
        # path. This gives additional SRAM headroom for compiler/link changes.
        for name, ret in [('daa_das', 'void'), ('aaa_aas', 'void'), ('step0f', 'int')]:
            needle = f'B86_HOT static {ret} {name}('
            src = one(src, needle, f'static {ATTR} {ret} {name}(',
                      f'cold legacy helper {name}')
        # No modifications to existing b86_step_internal(), 16-bit native
        # op lowering, or memory/code-cache allocations.
    else:
        raise RuntimeError('Unexpected source file: ' + relative)
    return src.replace('\n', nl).encode('utf-8')


def root_default() -> Path:
    return Path(r'C:\blitz86_v2') if os.name == 'nt' else HOME / 'blitz86_v2'


def check_tree(root: Path) -> None:
    for rel in FILES:
        if not (root / rel).is_file():
            raise RuntimeError(f'missing source file: {root / rel}')
    # Enforce prior layer's SHA manifest if this is its normal C:\blitzBUS
    # install, so the source really is the current known RM2 configuration.
    manifest = HOME / '.bb_386_rm2_v1_backup' / 'manifest.json'
    if manifest.is_file():
        m = json.loads(manifest.read_text('utf-8'))
        if m.get('root') == str(root.resolve()):
            for rel, val in m['edited'].items():
                if digest((root / rel).read_bytes()) != val['after']:
                    raise RuntimeError('RM2 edited source does not match original RM2 SHA: ' + rel)
            for rel, value in m['created'].items():
                if digest((root / rel).read_bytes()) != value:
                    raise RuntimeError('RM2 created source does not match original RM2 SHA: ' + rel)


def apply_to_tree(root: Path, commit: bool) -> None:
    if BACK.exists():
        raise RuntimeError('Fix already installed or stale backup; use verify')
    check_tree(root)
    before = {rel: (root / rel).read_bytes() for rel in FILES}
    after = {rel: edit(rel, raw) for rel, raw in before.items()}
    for rel in FILES:
        print(f'{rel}: anchors PASS, {len(before[rel])} -> {len(after[rel])} bytes, '
              f'newline={eol_of(before[rel])!r}')
    if not commit:
        print('PROBE PASS — no files modified')
        return
    manifest = {'tag': TAG, 'root': str(root.resolve()),
                'files': {rel: {'before': digest(before[rel]), 'after': digest(after[rel])}
                          for rel in FILES}}
    BACK.mkdir()
    written = []
    try:
        for rel, data in before.items():
            dest = BACK / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        (BACK / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        for rel, data in after.items():
            (root / rel).write_bytes(data)
            written.append(rel)
        verify(root)
    except Exception:
        for rel in written:
            (root / rel).write_bytes(before[rel])
        shutil.rmtree(BACK)
        raise
    print('APPLIED: 386 and rare 286 helpers forced into XIP flash; 232-KiB JIT cache unchanged')


def get_manifest(root: Path) -> dict:
    path = BACK / 'manifest.json'
    if not path.is_file():
        raise RuntimeError('Backup/manifest missing: fix not installed')
    m = json.loads(path.read_text('utf-8'))
    if m.get('tag') != TAG or m.get('root') != str(root.resolve()):
        raise RuntimeError('Backup is for another source tree')
    if set(m.get('files', {})) != set(FILES):
        raise RuntimeError('Manifest file list is unexpected')
    return m


def verify(root: Path) -> None:
    m = get_manifest(root)
    for rel, h in m['files'].items():
        if digest((root / rel).read_bytes()) != h['after']:
            raise RuntimeError('Current file changed since install: ' + rel)
        if digest((BACK / rel).read_bytes()) != h['before']:
            raise RuntimeError('Backup file changed: ' + rel)
    print('VERIFIED: 386 flash relocation ON, original RM2/RM1/RM0 backups intact')


def restore(root: Path) -> None:
    m = get_manifest(root)
    verify(root)
    # Do not remove backup unless all source files have been restored correctly.
    for rel in FILES:
        old = (BACK / rel).read_bytes()
        (root / rel).write_bytes(old)
        if digest((root / rel).read_bytes()) != m['files'][rel]['before']:
            raise RuntimeError('Exact-byte restoration failed: ' + rel)
    shutil.rmtree(BACK)
    print('RESTORED exact RM2 source; RM0/RM1/RM2 and other optimizations retained')


def selftest() -> None:
    # Source fixtures also exercise the 386 wrapper split and all 26 code
    # relocations, exact rollback, LF/CRLF, and wrong-checkout protection.
    global BACK, HOME
    old_back, old_home = BACK, HOME
    wrap = '''/* BB_386_RM0_V1 */
/* BB_386_RM1_V1 */
/* BB_386_RM2_V1 */
#include "i386_rm2.inc"
B86_HOT static void daa_das(B86Cpu *c, int sub) {}
B86_HOT static void aaa_aas(B86Cpu *c, int sub) {}
B86_HOT static int step0f(St *s) { return 0; }
B86_HOT static int b86_step_internal(B86Cpu *c) { return 0; }
B86_HOT int b86_step(B86Cpu *c)
{
    if (c->model < B86_CPU_386) return b86_step_internal(c);
    uint32_t hi[8];
    for (unsigned i = 0; i < 8; ++i) hi[i] = c->r[i] & 0xFFFF0000u;
    uint16_t ip = (uint16_t)c->ip;
    int operand32 = 0;
    for (unsigned k = 0; k < 15; ++k) {
        uint8_t op = rd8(c, B86_CS, ip++);
        if (op == 0x66) { operand32 = 1; continue; }
        if (op == 0x67 || op == 0x26 || op == 0x2E || op == 0x36 ||
            op == 0x3E || op == 0xF0 || op == 0xF1 || op == 0xF2 || op == 0xF3)
            continue;
        break;
    }
    int rc = b86_step_internal(c);
    if (!operand32) for (unsigned i = 0; i < 8; ++i) c->r[i] = (c->r[i] & 0xFFFFu) | hi[i];
    return rc;
}
'''
    for nl in ['\n', '\r\n']:
        raw = wrap.replace('\n', nl).encode()
        changed = edit('src/interp.c', raw)
        assert changed != raw
        assert changed.count(f'B86_HOT int b86_step(B86Cpu *c)'.encode()) == 1
        assert f'B86_HOT static int b86_step_internal'.encode() in changed
        assert f'B86_COLD static'.encode() not in changed
        assert eol_of(changed) == nl
        for rel, ct in [('src/i386_rm0.inc', 9), ('src/i386_rm1.inc', 11), ('src/i386_rm2.inc', 6)]:
            original = (f'/* TEST */\n' + 'B86_COLD static int fun(int x);\n' * ct).replace('\n', nl).encode()
            patched = edit(rel, original)
            assert patched.count(b'__attribute__') == ct
            assert eol_of(patched) == nl
    try:
        with tempfile.TemporaryDirectory() as p:
            HOME = Path(p)
            BACK = HOME / '.backup'
            root = HOME / 'blitz86_v2'
            (root / 'src').mkdir(parents=True)
            (root / 'src/interp.c').write_text(wrap)
            for rel, ct in [('src/i386_rm0.inc', 9), ('src/i386_rm1.inc', 11), ('src/i386_rm2.inc', 6)]:
                (root / rel).write_text('B86_COLD static int f(int x);\n' * ct)
            apply_to_tree(root, True)
            try:
                apply_to_tree(root, True)
                raise AssertionError('second install should fail')
            except RuntimeError:
                pass
            restore(root)
            assert (root / 'src/interp.c').read_text() == wrap
            assert not BACK.exists()
    finally:
        BACK, HOME = old_back, old_home
    print('SELFTEST PASS: flash sections, model guards, LF/CRLF, install/verify/restore')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['selftest', 'probe', 'apply', 'verify', 'restore'])
    ap.add_argument('--blitz86', type=Path, default=root_default())
    a = ap.parse_args()
    if a.action == 'selftest':
        selftest()
        return
    root = a.blitz86.resolve()
    {'probe': lambda r: apply_to_tree(r, False),
     'apply': lambda r: apply_to_tree(r, True),
     'verify': verify, 'restore': restore}[a.action](root)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(1)
