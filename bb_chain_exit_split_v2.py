#!/usr/bin/env python3
"""blitzBUS / blitz86: reversible native-exit reason split (V2).

Save to C:\\blitzBUS\\bb_chain_exit_split_v2.py

    python bb_chain_exit_split_v2.py probe
    python bb_chain_exit_split_v2.py apply
    python bb_chain_exit_split_v2.py verify
    python bb_chain_exit_split_v2.py restore

Supports chain audit instrumentation already inserted before switch(r).
No eviction, chaining, translator eligibility, PSRAM, or SRAM buffer changes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
MARK = 'BB_CHAIN_EXIT_SPLIT_V2'
MANIFEST = ROOT / 'bb_chain_exit_split_v2_manifest.json'

def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def unpack(data: bytes):
    bom = data.startswith(b'\xef\xbb\xbf')
    text = data.decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in text else '\n'
    return text, newline, bom

def pack(s: str, bom: bool) -> bytes:
    return (b'\xef\xbb\xbf' if bom else b'') + s.encode('utf-8')

def replace_exact(s: str, before: str, after: str, label: str) -> str:
    count = s.count(before)
    if count != 1:
        raise RuntimeError(f'{label}: expected one anchor, found {count}')
    return s.replace(before, after, 1)

def replace_pattern(s: str, pattern: str, replacement: str, label: str) -> str:
    matches = list(re.finditer(pattern, s, re.M))
    if len(matches) != 1:
        raise RuntimeError(f'{label}: expected one structural match, found {len(matches)}')
    m=matches[0]
    return s[:m.start()] + replacement + s[m.end():]

def edit(name: str, s: str, nl: str) -> str:
    if MARK in s or 'BB_CHAIN_EXIT_SPLIT_V1' in s:
        raise RuntimeError(f'{name}: an exit-split variant appears already installed')
    if name == 'backend':
        before='enum { XR_LOOKUP = 0, XR_CHAIN = 1, XR_HALT = 2, XR_IRQ = 3, XR_RETFILL = 4 };'
        after='''/* BB_CHAIN_EXIT_SPLIT_V2: distinguish equivalent return paths to the C dispatcher. */
enum { XR_LOOKUP = 0, XR_CHAIN = 1, XR_HALT = 2, XR_IRQ = 3, XR_RETFILL = 4,
       XR_DYNAMIC = 5, XR_FASTMISS = 6 };'''.replace('\n',nl)
        return replace_exact(s,before,after,'backend: exit enum')
    if name == 'thumb':
        # The old x_miss points to the same epilogue stub as dynamic exits.
        # Both will still return to the same C dispatcher, with different codes.
        pattern=r'(?m)^([ \t]*)e->x_dynexit = e->p;\r?\n[ \t]*movw\(e, R12, XR_LOOKUP\);\r?\n[ \t]*emit_b\(e, e->x_epilogue\);\r?\n[ \t]*e->x_miss = e->x_dynexit;[^\r\n]*'
        matches=list(re.finditer(pattern,s,re.M))
        if len(matches)!=1:
            raise RuntimeError(f'thumb: shared dynexit/fastmiss stub expected once, found {len(matches)}')
        ind=matches[0].group(1)
        after='''/* BB_CHAIN_EXIT_SPLIT_V2: separate reasons, identical C dispatcher behavior. */
e->x_dynexit = e->p;
movw(e, R12, XR_DYNAMIC);
emit_b(e, e->x_epilogue);
e->x_miss = e->p;
movw(e, R12, XR_FASTMISS);
emit_b(e, e->x_epilogue);'''
        after=nl.join(ind+line for line in after.splitlines())
        m=matches[0]
        return s[:m.start()]+after+s[m.end():]
    if name == 'jit':
        # V1 assumed switch(r) and case XR_HALT were adjacent. Chain-audit adds
        # extra code around the switch, and other local diagnostic editions vary.
        # Anchor just the unique chain case, restricted to b86_jit_run().
        fn='B86_HOT int b86_jit_run('
        if s.count(fn)!=1:raise RuntimeError('jit: expected one b86_jit_run function')
        start=s.index(fn)
        tail=s[start:]
        if 'switch (r)' not in tail or 'case XR_HALT:' not in tail:
            raise RuntimeError('jit: exit-reason switch is not recognizable')
        pattern=r'(?m)^([ \t]*)case XR_CHAIN:'
        ms=list(re.finditer(pattern,tail,re.M))
        if len(ms)!=1:
            raise RuntimeError(f'jit: XR_CHAIN case expected once inside b86_jit_run, found {len(ms)}')
        m=ms[0]; ind=m.group(1)
        insert='''/* BB_CHAIN_EXIT_SPLIT_V2: count and dispatch exactly as XR_LOOKUP did. */
case XR_DYNAMIC: j->st.exit_dynamic++; break;
case XR_FASTMISS: j->st.exit_native_miss++; break;
case XR_LOOKUP: j->st.exit_direct_lookup++; break;
'''
        insert=''.join(ind+line+nl for line in insert.splitlines())
        tail=tail[:m.start()]+insert+tail[m.start():]
        return s[:start]+tail
    if name=='public':
        pattern=r'(?m)^([ \t]*)uint64_t dispatches;([ \t]*)(\r?\n)([ \t]*)uint64_t translate_us;'
        ms=list(re.finditer(pattern,s,re.M))
        if len(ms)!=1:raise RuntimeError(f'public: dispatches / translate_us anchor expected once, found {len(ms)}')
        m=ms[0]; ind=m.group(1); after=(f'{ind}uint64_t dispatches;{nl}'
            f'{ind}/* BB_CHAIN_EXIT_SPLIT_V2: cumulative return-reason counters. */{nl}'
            f'{ind}uint64_t exit_dynamic, exit_native_miss, exit_direct_lookup;{nl}'
            f'{m.group(4)}uint64_t translate_us;')
        return s[:m.start()]+after+s[m.end():]
    if name=='live':
        old='    printf("[bb-jit] native-ms='
        after='''    /* BB_CHAIN_EXIT_SPLIT_V2: cumulative native exit reasons (not bb-jit deltas). */
    printf("[bb-exit-split] dynamic=%llu native-fast-miss=%llu direct-lookup=%llu total-classified=%llu\\n",
           (unsigned long long)s->exit_dynamic,
           (unsigned long long)s->exit_native_miss,
           (unsigned long long)s->exit_direct_lookup,
           (unsigned long long)(s->exit_dynamic + s->exit_native_miss + s->exit_direct_lookup));
'''.replace('\n',nl) + old
        return replace_exact(s,old,after,'live: periodic JIT reporting')
    raise RuntimeError('Unknown file: '+name)

def files(blitz:Path):
    return {'backend':blitz/'src'/'backend.h',
            'thumb':blitz/'src'/'be_t2.c',
            'jit':blitz/'src'/'jit.c',
            'public':blitz/'include'/'b86.h',
            'live':ROOT/'src'/'bb_live.c'}

def planned(blitz:Path):
    plan={}
    for name,path in files(blitz).items():
        if not path.is_file():raise RuntimeError(f'Missing {name}: {path}')
        old=path.read_bytes()
        s,nl,bom=unpack(old)
        new=pack(edit(name,s,nl),bom)
        if old==new:raise RuntimeError(f'{name}: no source change generated')
        backup=path.with_name(path.name+'.chain-exit-split-v2.bak')
        if backup.exists():raise RuntimeError(f'{name}: backup exists, refusing overwrite: {backup}')
        plan[name]={'path':path,'backup':backup,'before':old,'after':new,
                     'before_sha':digest(old),'after_sha':digest(new)}
    return plan

def probe(blitz:Path):
    for name,path in files(blitz).items():
        if not path.is_file():
            print(f'{name:8s} MISSING {path}')
            continue
        try:
            old=path.read_bytes();s,nl,bom=unpack(old)
            changed=edit(name,s,nl)
            print(f'{name:8s} READY {path} (+{len(changed)-len(s)} characters)')
        except Exception as ex:
            print(f'{name:8s} STOP: {ex}')

def apply(blitz:Path):
    if MANIFEST.exists():raise RuntimeError(f'Manifest already exists: {MANIFEST}; use verify/restore')
    p=planned(blitz)  # No file changes until every anchor has passed.
    written=[]
    try:
        for name,item in p.items():
            item['backup'].write_bytes(item['before'])
            written.append(('backup',item['backup']))
        for name,item in p.items():
            item['path'].write_bytes(item['after'])
            written.append(('source',item['path']))
        desc={name:dict(file=str(v['path']),backup=str(v['backup']),
                        before_sha=v['before_sha'],after_sha=v['after_sha'])
              for name,v in p.items()}
        MANIFEST.write_text(json.dumps({'marker':MARK,'files':desc},indent=2),encoding='utf-8')
    except BaseException:
        for name,item in p.items():
            if item['backup'].is_file():
                item['path'].write_bytes(item['before'])
                item['backup'].unlink()
        raise
    print('Installed', MARK, '(5 sources; all earlier diagnostics retained).')
    verify()

def verify():
    if not MANIFEST.is_file():raise RuntimeError('Manifest missing; apply has not succeeded')
    d=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if d.get('marker')!=MARK:raise RuntimeError('Unexpected manifest marker')
    for name,item in d['files'].items():
        path=Path(item['file']);backup=Path(item['backup'])
        if not path.is_file() or digest(path.read_bytes())!=item['after_sha']:
            raise RuntimeError(f'{name}: source changed after apply; refusing restoration: {path}')
        if not backup.is_file() or digest(backup.read_bytes())!=item['before_sha']:
            raise RuntimeError(f'{name}: backup missing or modified: {backup}')
        print(f'{name:8s} OK {path}')
    print('Five source edits verified; firmware compilation and hardware behavior not verified.')

def restore():
    verify()
    d=json.loads(MANIFEST.read_text(encoding='utf-8'))
    for name,item in d['files'].items():
        Path(item['file']).write_bytes(Path(item['backup']).read_bytes())
        print('Restored',name)
    for item in d['files'].values():Path(item['backup']).unlink()
    MANIFEST.unlink()
    print('All five previous source files restored. Rebuild to restore previous firmware.')

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command',choices=('probe','apply','verify','restore'))
    ap.add_argument('--blitz86',type=Path,default=Path(r'C:\blitz86_v2'))
    a=ap.parse_args()
    try:
        if a.command=='probe':probe(a.blitz86)
        elif a.command=='apply':apply(a.blitz86)
        elif a.command=='verify':verify()
        elif a.command=='restore':restore()
    except (RuntimeError,ValueError,UnicodeError,OSError) as ex:
        print('ERROR:',ex,file=sys.stderr)
        sys.exit(1)
if __name__=='__main__':main()
