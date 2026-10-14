#!/usr/bin/env python3
"""blitz86 386 PM0 + RP2350 probe installer (RM3 prerequisite).

Extract this entire bundle to C:\\blitzBUS. Full files; no Git patches.

  python .\\bb_386_pm0_v1.py selftest
  python .\\bb_386_pm0_v1.py probe
  python .\\bb_386_pm0_v1.py apply
  python .\\bb_386_pm0_v1.py verify
  python .\\bb_386_pm0_v1.py restore

The installer performs byte-exact SHA256 backup/rollback in
C:\\blitzBUS\\.bb_386_pm0_v1_backup; it does not alter older RM installers.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sys, tempfile
from pathlib import Path

TAG = 'BB_386_PM0_V1'
HERE = Path(__file__).resolve().parent
BACKUP = HERE / '.bb_386_pm0_v1_backup'
EDITED = {'blitz86/src/interp.c': 'interp', 'blitzBUS/src/bb_live.c': 'live'}
CREATED = {
    'blitz86/include/b86_pm0.h': 'b86_pm0.h',
    'blitz86/src/i386_pm0.inc': 'i386_pm0.inc',
    'blitz86/tests/bb_386_pm0_smoke.c': 'bb_386_pm0_smoke.c',
    'blitzBUS/src/bb_386_pico_probe.inc': 'bb_386_pico_probe.inc',
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def newlines(data: bytes) -> str:
    if b'\r\n' in data and b'\n' in data.replace(b'\r\n', b''):
        raise ValueError('mixed CRLF/LF input')
    if b'\r' in data.replace(b'\r\n', b''):
        raise ValueError('CR-only line endings')
    return '\r\n' if b'\r\n' in data else '\n'


def unique_replace(source: str, old: str, new: str, label: str) -> str:
    n = source.count(old)
    if n != 1:
        raise ValueError(f'{label}: expected exactly 1 anchor, got {n}')
    return source.replace(old, new, 1)


def transform(kind: str, data: bytes) -> bytes:
    eol = newlines(data)
    source = data.decode('utf-8').replace('\r\n','\n')
    if TAG in source:
        raise ValueError(f'{kind}: PM0 already applied')
    if kind == 'interp':
        source = unique_replace(
            source, '#include "i386_rm3.inc"',
            '#include "i386_rm3.inc"\n'
            f'/* {TAG}: GDT descriptor helpers in flash, no PE switch. */\n'
            '#include "i386_pm0.inc"', 'RM3 include')
    elif kind == 'live':
        source = unique_replace(
            source, '#include "b86.h"',
            '#include "b86.h"\n'
            f'/* {TAG}: optional 386 interpreter smoke, isolated from DOS. */\n'
            '#ifndef BB386_PICO_PROBE\n#define BB386_PICO_PROBE 1\n#endif\n'
            '#if BB386_PICO_PROBE\n#include "bb_386_pico_probe.inc"\n#endif', 'blitz86 header')
        source = unique_replace(
            source, '    b86_init(&C, rt->cpu.memory);',
            '    b86_init(&C, rt->cpu.memory);\n'
            '#if BB386_PICO_PROBE && defined(PICO_ON_DEVICE) && PICO_ON_DEVICE\n'
            '    /* Private PSRAM CPU; guest HMA bytes saved/restored; never changes C. */\n'
            '    (void)bb386_test_run(rt->cpu.memory);\n'
            '#endif', 'CPU initialization')
    else:
        raise ValueError('bad transform kind')
    return source.replace('\n',eol).encode('utf-8')


def dest(roots: dict[str,Path], key: str) -> Path:
    name, sub = key.split('/',1)
    return roots[name] / sub


def read_manifest(roots: dict[str,Path]) -> dict:
    p = BACKUP / 'manifest.json'
    if not p.is_file(): raise ValueError('PM0 manifest missing; not installed')
    m = json.loads(p.read_text(encoding='utf-8'))
    if m.get('tag') != TAG:
        raise ValueError('PM0 manifest tag mismatch')
    for name, root in roots.items():
        if m['roots'].get(name) != str(root.resolve()):
            raise ValueError(f'manifest belongs to another {name} checkout')
    return m


def probe(roots: dict[str,Path]) -> None:
    if BACKUP.exists():
        raise ValueError('PM0 backup already exists; use verify or restore')
    for key,kind in EDITED.items():
        p=dest(roots,key)
        if not p.is_file(): raise ValueError(f'missing {p}')
        raw=p.read_bytes()
        if kind=='interp' and ('BB_386_RM3_V1' not in raw.decode('utf8')):
            raise ValueError('RM3 is required; install RM3 first')
        converted=transform(kind,raw)
        print(f'{key}: anchors PASS, {len(raw)} -> {len(converted)} bytes, EOL={newlines(raw)!r}')
    for key,bundle in CREATED.items():
        if dest(roots,key).exists(): raise ValueError('refusing to overwrite '+key)
        if not (HERE / bundle).is_file(): raise ValueError('bundle incomplete: missing '+bundle)
        print(f'{key}: will create')
    print('PROBE PASS - no files written')


def verify(roots: dict[str,Path]) -> None:
    m=read_manifest(roots)
    for key,v in m['edited'].items():
        if sha(dest(roots,key).read_bytes()) != v['after']:
            raise ValueError('modified installed source: '+key)
        if sha((BACKUP/key).read_bytes()) != v['before']:
            raise ValueError('modified backup: '+key)
    for key,h in m['created'].items():
        if sha(dest(roots,key).read_bytes()) != h:
            raise ValueError('modified PM0 file: '+key)
    print('VERIFIED PM0: GDT decoder and Pico 386 probe installed; backups intact')


def apply(roots: dict[str,Path]) -> None:
    probe(roots)
    old={key:dest(roots,key).read_bytes() for key in EDITED}
    new={key:transform(EDITED[key],buf) for key,buf in old.items()}
    created={key:(HERE/bundle).read_bytes() for key,bundle in CREATED.items()}
    manifest={'tag':TAG,'roots':{name:str(root.resolve()) for name,root in roots.items()},
              'edited':{key:{'before':sha(old[key]),'after':sha(new[key])} for key in EDITED},
              'created':{key:sha(buf) for key,buf in created.items()}}
    BACKUP.mkdir(parents=True)
    changed=[]
    try:
        for key,buf in old.items():
            path=BACKUP/key
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(buf)
        (BACKUP/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
        for key,buf in {**new,**created}.items():
            target=dest(roots,key)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(buf)
            changed.append(key)
        verify(roots)
    except Exception:
        for key in changed:
            if key in old: dest(roots,key).write_bytes(old[key])
            else: dest(roots,key).unlink(missing_ok=True)
        shutil.rmtree(BACKUP)
        raise
    print('APPLIED PM0: 386 boot test enabled, 286 native path/cache untouched')


def restore(roots: dict[str,Path]) -> None:
    m=read_manifest(roots)
    verify(roots)
    for key in EDITED:
        dest(roots,key).write_bytes((BACKUP/key).read_bytes())
        if sha(dest(roots,key).read_bytes()) != m['edited'][key]['before']:
            raise ValueError('restore mismatch '+key)
    for key in CREATED: dest(roots,key).unlink()
    shutil.rmtree(BACKUP)
    print('RESTORED PM0 byte-for-byte; RM3, RM2, existing 286 JIT retained')


def selftest() -> None:
    global HERE, BACKUP
    old_here, old_backup=HERE,BACKUP
    try:
        for eol,version in [('\n','lf'),('\r\n','crlf')]:
            with tempfile.TemporaryDirectory() as td:
                HERE=Path(td)
                BACKUP=HERE/'.bb_386_pm0_v1_backup'
                roots={'blitz86':HERE/'blitz86','blitzBUS':HERE/'blitzBUS'}
                source={
                    'blitz86/src/interp.c': '/* BB_386_RM3_V1 */\n#include "i386_rm3.inc"\n',
                    'blitzBUS/src/bb_live.c': '#include "b86.h"\n    b86_init(&C, rt->cpu.memory);\n',
                }
                for key,content in source.items():
                    target=dest(roots,key)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(content.replace('\n',eol).encode('utf8'))
                raw={key:dest(roots,key).read_bytes() for key in EDITED}
                for bundle in CREATED.values():
                    (HERE/bundle).write_bytes((old_here/bundle).read_bytes())
                probe(roots); apply(roots); verify(roots); restore(roots)
                assert all(dest(roots,k).read_bytes()==v for k,v in raw.items()),version
                assert all(not dest(roots,k).exists() for k in CREATED),version
    finally:
        HERE,BACKUP=old_here,old_backup
    print('SELFTEST PASS: LF/CRLF, SHA checks, exact install and restore')


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    parser.add_argument('--blitz86',type=Path,default=Path(r'C:\blitz86_v2'))
    parser.add_argument('--blitzBUS',type=Path,default=Path(r'C:\blitzBUS'))
    args=parser.parse_args()
    roots={'blitz86':args.blitz86.resolve(),'blitzBUS':args.blitzBUS.resolve()}
    if args.action=='selftest': selftest()
    else: {'probe':probe,'apply':apply,'verify':verify,'restore':restore}[args.action](roots)

if __name__=='__main__':
    try: main()
    except (ValueError,RuntimeError,OSError,UnicodeError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        sys.exit(1)
