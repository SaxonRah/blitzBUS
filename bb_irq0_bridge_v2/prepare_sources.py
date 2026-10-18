#!/usr/bin/env python3
"""Stage all current blitz86 interpreter includes for the IRQ0 host bridge.

Only writes to --out/blitz86. Never edits the original blitz86 checkout,
microDOS checkout, PIC/PIT source, firmware, or any DOS images.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys
import tempfile

INCLUDE = re.compile(r'^\s*#\s*include\s*"([^"\n]+)"', re.M)
ATTRIBUTE = re.compile(r'__attribute__\s*\(')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remove_gnu_attributes(source: str) -> tuple[str, int]:
    """Remove GNU __attribute__(...) hints from a disposable host copy."""
    changed = 0
    at = 0
    out = []
    while (match := ATTRIBUTE.search(source, at)):
        out.append(source[at:match.start()])
        i = match.end() - 1
        level = 0
        quote = None
        escaped = False
        while i < len(source):
            ch = source[i]
            if quote:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == quote:
                    quote = None
            elif ch in ('"', "'"):
                quote = ch
            elif ch == '(':
                level += 1
            elif ch == ')':
                level -= 1
                if level == 0:
                    break
            i += 1
        else:
            raise ValueError('Unbalanced GNU __attribute__ expression')
        out.append(' ')
        changed += 1
        at = i + 1
    out.append(source[at:])
    return ''.join(out), changed


def include_path(base: pathlib.Path, text: str) -> pathlib.Path:
    name = pathlib.PurePosixPath(text.replace('\\', '/'))
    if name.is_absolute() or not name.parts or any(p in ('.', '..') for p in name.parts):
        raise ValueError(f'Unsafe local include path: {text!r}')
    return base.joinpath(*name.parts)


def discover(blitz: pathlib.Path) -> dict[pathlib.Path, tuple[pathlib.Path, bytes]]:
    """Walk quote-includes recursively, resolving them exactly as local source.

    The two repo trees are also compiler -I roots. Staging both the referenced
    .inc modules and their .h files avoids accidentally including unconverted
    GCC headers from the original checkout under MSVC.
    """
    src, headers = blitz/'src', blitz/'include'
    root = src/'interp.c'
    if not root.is_file():
        raise FileNotFoundError(root)
    if not (headers/'b86.h').is_file():
        raise FileNotFoundError(headers/'b86.h')
    pending = [root]
    resolved = {}
    sources = {}
    while pending:
        path = pending.pop(0).resolve()
        if path in resolved:
            continue
        try:
            relative = path.relative_to(src.resolve())
        except ValueError:
            try:
                relative = path.relative_to(headers.resolve())
            except ValueError:
                raise ValueError(f'Include escaped blitz86 src/include: {path}')
        if not path.is_file():
            raise FileNotFoundError(path)
        original = path.read_bytes()
        try:
            decoded = original.decode('utf-8-sig')
        except UnicodeError as exc:
            raise ValueError(f'Non-UTF8 source: {path}') from exc
        if relative in sources and sources[relative][0] != path:
            raise ValueError(f'Conflicting source and header for {relative}')
        sources[relative] = (path, original)
        resolved[path] = relative
        for quoted in INCLUDE.findall(decoded):
            name = quoted.replace('\\', '/')
            candidates = [include_path(path.parent, name),
                          include_path(src, name),
                          include_path(headers, name)]
            picked = next((c for c in candidates if c.is_file()), None)
            if picked is None:
                raise FileNotFoundError(f'{path.name} requires missing include {quoted!r}')
            pending.append(picked)
    return sources


def prepare(blitz: pathlib.Path, out: pathlib.Path, msvc: bool = False) -> None:
    sources = discover(blitz)
    if len(sources) < 2:
        raise ValueError('Discovery did not find any interpreter dependencies')
    files = {}
    total_attrs = 0
    for relative, (path, original) in sorted(sources.items(), key=lambda p: str(p[0])):
        transformed = original
        stripped = 0
        if msvc:
            txt, stripped = remove_gnu_attributes(original.decode('utf-8-sig'))
            if relative.as_posix() == 'interp.c':
                txt = '#ifndef __builtin_expect\n#define __builtin_expect(x,y) (x)\n#endif\n' + txt
            transformed = txt.encode('utf-8')
        files[relative] = transformed
        total_attrs += stripped
        print(f'{str(relative):<22} original sha256={sha(original)} '
              f'stage_bytes={len(transformed)} attrs_stripped={stripped}')
    staged = out/'blitz86'
    for relative, transformed in files.items():
        target = staged/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(transformed)
        if target.read_bytes() != transformed:
            raise OSError(f'Staging verification failed: {target}')
    print(f'STAGE PASS: {len(files)} local blitz86 files, '
          f'msvc={msvc}, attributes stripped={total_attrs}')
    print('All quoted interpreter dependencies staged; original source directories unchanged.')


def selftest() -> None:
    cases = [
        'static __attribute__((noinline,cold,section(".text.flash"))) int fn(void) { return 42; }',
        '__attribute__((always_inline)) void x(void) {}',
        'int x; /* __attribute__((noinline)) */ int y;',
    ]
    for src in cases:
        clean, count = remove_gnu_attributes(src)
        assert count >= 1 and '__attribute__' not in clean
        assert clean.count('{') == src.count('{')
    assert remove_gnu_attributes('int x=5;') == ('int x=5;', 0)
    with tempfile.TemporaryDirectory() as root:
        base = pathlib.Path(root)
        (base/'src').mkdir()
        (base/'include').mkdir()
        (base/'src'/'interp.c').write_text('#include "b86.h"\n#include "i386_pm1.inc"\n#include "i386_pm23.inc"\nint value;\n')
        (base/'src'/'i386_pm1.inc').write_text('#include "b86_pm1.h"\n#define H __attribute__((cold))\n')
        (base/'src'/'i386_pm23.inc').write_text('#include "b86_pm23.h"\n')
        (base/'include'/'b86.h').write_text('#include <stdint.h>\n')
        (base/'include'/'b86_pm1.h').write_text('int pm1;\n')
        (base/'include'/'b86_pm23.h').write_text('#include "b86_pm1.h"\nint pm23;\n')
        out = base/'out'
        prepare(base, out, True)
        staged = out/'blitz86'
        for name in ('interp.c', 'i386_pm1.inc', 'i386_pm23.inc',
                     'b86.h', 'b86_pm1.h', 'b86_pm23.h'):
            assert (staged/name).is_file(), name
        assert '__attribute__' not in (staged/'i386_pm1.inc').read_text()
        assert '__builtin_expect' in (staged/'interp.c').read_text()
        # Discovery failure must occur before a staged partial tree is created.
        (base/'src'/'i386_pm23.inc').write_text('#include "missing.h"\n')
        try:
            prepare(base, base/'other_out', True)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError('Missing include must be rejected')
        assert not (base/'other_out').exists()
    print('SELFTEST PASS: recursive quoted includes, GNU attributes, and missing-dependency refusal')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'selftest'])
    parser.add_argument('--blitz', type=pathlib.Path, default=pathlib.Path(r'C:\blitz86_v2'))
    parser.add_argument('--out', type=pathlib.Path)
    parser.add_argument('--msvc', action='store_true')
    args = parser.parse_args()
    if args.action == 'selftest':
        selftest()
        return
    if args.out is None:
        parser.error('prepare requires --out')
    prepare(args.blitz.resolve(), args.out.resolve(), args.msvc)


if __name__ == '__main__':
    try:
        main()
    except (FileNotFoundError, UnicodeError, OSError, ValueError, AssertionError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
