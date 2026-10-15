#!/usr/bin/env python3
"""Read actual blitz86 sources; stage host MSVC-compatible copies in diagnostic build/ only.

No files in C:\\blitz86_v2, C:\\microDOS, or C:\\blitzBUS\\src are changed.
For MSVC only, remove GNU function attributes from staged source copies and
replace __builtin_expect with a portable no-op macro. Semantics remain intact.
"""
import argparse
import hashlib
import pathlib
import re
import shutil
import sys

NAMES = ('interp.c','i386_rm0.inc','i386_rm1.inc','i386_rm2.inc','i386_rm3.inc','i386_pm0.inc')


def sha(data): return hashlib.sha256(data).hexdigest()


def remove_gnu_attributes(source):
    expr = re.compile(r'__attribute__\s*\(')
    changed=0
    at=0
    out=[]
    while (m:=expr.search(source, at)):
        out.append(source[at:m.start()])
        i=m.end()-1
        level=0
        quote=None
        escaped=False
        while i<len(source):
            ch=source[i]
            if quote:
                if escaped: escaped=False
                elif ch=='\\':escaped=True
                elif ch==quote:quote=None
            elif ch in ('"',"'"):
                quote=ch
            elif ch=='(':level+=1
            elif ch==')':
                level-=1
                if level==0:break
            i+=1
        else: raise ValueError('Unbalanced GNU __attribute__ expression')
        out.append(' ')
        changed+=1
        at=i+1
    out.append(source[at:])
    return ''.join(out),changed


def prepare(blitz, out, msvc=False):
    src=blitz/'src'
    header=blitz/'include'/'b86.h'
    if not header.is_file():raise FileNotFoundError(header)
    staged=out/'blitz86'
    staged.mkdir(parents=True,exist_ok=True)
    total_attr=0
    for name in NAMES:
        path=src/name
        if not path.is_file():raise FileNotFoundError(path)
        original=path.read_bytes()
        # Preserve the current source hash for diagnosis if the local checkout diverges.
        new=original
        n=0
        if msvc:
            txt=original.decode('utf-8-sig')
            txt,n=remove_gnu_attributes(txt)
            if name=='interp.c':
                txt='#ifndef __builtin_expect\n#define __builtin_expect(x,y) (x)\n#endif\n'+txt
            new=txt.encode('utf-8')
        staged.joinpath(name).write_bytes(new)
        total_attr+=n
        print(f'{name:<19} original sha256={sha(original)} stage_bytes={len(new)} attrs_stripped={n}')
    header_orig=header.read_bytes()
    header_stage=header_orig
    nheader=0
    if msvc:
        txt=header_orig.decode('utf-8-sig')
        txt,nheader=remove_gnu_attributes(txt)
        header_stage=txt.encode('utf-8')
    staged.joinpath('b86.h').write_bytes(header_stage)
    total_attr+=nheader
    print(f'b86.h original sha256={sha(header_orig)} attrs_stripped={nheader}')
    print(f'STAGE PASS: {len(NAMES)+1} local blitz86 files, msvc={msvc}, attributes stripped={total_attr}')
    print('Original source directories unchanged.')


def selftest():
    cases=[
        'static __attribute__((noinline,cold,section(".text.flash"))) int fn(void) { return 42; }',
        '__attribute__((always_inline)) void x(void) {}',
        'int x; /* __attribute__((noinline)) */ int y;',
    ]
    for x in cases:
        s,n=remove_gnu_attributes(x)
        assert n>=1 and '__attribute__' not in s
        assert s.count('{')==x.count('{')
    assert remove_gnu_attributes('int value = 5;')==('int value = 5;',0)
    print('SELFTEST PASS: GNU attribute scanner (nested attrs, comments, balanced delimiters)')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['prepare','selftest'])
    p.add_argument('--blitz',type=pathlib.Path,default=pathlib.Path(r'C:\blitz86_v2'))
    p.add_argument('--out',type=pathlib.Path)
    p.add_argument('--msvc',action='store_true')
    args=p.parse_args()
    if args.action=='selftest':selftest();return
    if args.out is None:p.error('prepare requires --out')
    prepare(args.blitz.resolve(),args.out.resolve(),args.msvc)

if __name__=='__main__':
    try:main()
    except (FileNotFoundError,UnicodeError,OSError,ValueError,AssertionError) as ex:
        print('ERROR: '+str(ex),file=sys.stderr);sys.exit(1)
