#!/usr/bin/env python3
"""blitz86 exit hotspot diagnostic, reversible full-source instrumentation.

Requires bb_chain_exit_split_v2.py already applied and verified.
Adds distinct reasons for nonzero interpreter-helper return, DS guard
failure, and dead-block stub fallback. Native behavior is preserved; the
result still returns to the same dispatcher on each of these paths.

Save as C:\\blitzBUS\\bb_exit_hotspot_v1.py
  python bb_exit_hotspot_v1.py probe
  python bb_exit_hotspot_v1.py apply
  python bb_exit_hotspot_v1.py verify
  python bb_exit_hotspot_v1.py analyze --log logs\\bb-live-*-console.txt
  python bb_exit_hotspot_v1.py restore

No git patch. Source bytes backed up before changes. Existing profiling,
PSRAM arrangement, compilation settings, and eviction logic are unchanged.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
TAG='BB_EXIT_HOTSPOT_V1'
MANIFEST=ROOT/'bb_exit_hotspot_v1_manifest.json'

def sha(b):return hashlib.sha256(b).hexdigest()
def decode(b):
    bom=b.startswith(b'\xef\xbb\xbf')
    s=b.decode('utf-8-sig')
    return s,'\r\n' if '\r\n' in s else '\n',bom

def encode(s,bom):return (b'\xef\xbb\xbf' if bom else b'')+s.encode('utf-8')
def once(s,old,new,label):
    n=s.count(old)
    if n!=1:raise RuntimeError(f'{label}: expected exactly one anchor, found {n}')
    return s.replace(old,new,1)

def edit(kind,s,nl):
    if TAG in s: raise RuntimeError(f'{kind}: diagnostic is already present')
    if 'BB_CHAIN_EXIT_SPLIT_V2' not in s:raise RuntimeError(f'{kind}: V2 split marker missing')
    if kind=='backend':
        old='XR_FASTMISS = 6 };'
        new='XR_FASTMISS = 6, XR_STEP_EXIT = 7, XR_DS_GUARD = 8, XR_DEAD_STUB = 9 }; /* '+TAG+' */'
        return once(s,old,new,'backend enum')
    if kind=='thumb':
        start=s.find('e->x_step = e->p;')
        stop=s.find('e->x_lookup = e->p;',start)
        if start<0 or stop<0:raise RuntimeError('thumb: x_step/x_lookup control path missing')
        mid=s[start:stop]
        old='emit_b(e, e->x_dynexit);'
        new=('/* '+TAG+': same epilogue, distinct reason for step helper nonzero. */'+nl+
             '    movw(e, R12, XR_STEP_EXIT);'+nl+'    emit_b(e, e->x_epilogue);')
        mid=once(mid,old,new,'thumb step slow exit')
        return s[:start]+mid+s[stop:]
    if kind=='jit':
        old='be_exit_ip_imm(e, ip, XR_LOOKUP);'
        matches=[m.start() for m in re.finditer(re.escape(old),s)]
        if len(matches)!=2:raise RuntimeError(f'jit: expected 2 explicit lookup stubs, found {len(matches)}')
        p_ds=s.find('be_call_light(e, (void *)b86h_dsmiss')
        p_dead=s.find('b->dead_stub = e->p;')
        if not(p_ds>=0 and p_ds<matches[0] and matches[0]<p_dead<matches[1]):
            raise RuntimeError('jit: cannot prove ordering of DS guard and dead stub')
        s=(s[:matches[1]]+s[matches[1]:].replace(old,'be_exit_ip_imm(e, ip, XR_DEAD_STUB); /* '+TAG+' */',1))
        s=(s[:matches[0]]+s[matches[0]:].replace(old,'be_exit_ip_imm(e, ip, XR_DS_GUARD); /* '+TAG+' */',1))
        # Preserve the existing chain-audit aggregate when we split lookup reasons.
        agg='else if (r == XR_LOOKUP) ++bb_chain_audit[CH_EXIT_LOOKUP];'
        if agg in s:
            s=once(s,agg,'else if (r == XR_LOOKUP || r == XR_DS_GUARD || r == XR_DEAD_STUB) ++bb_chain_audit[CH_EXIT_LOOKUP]; /* '+TAG+' */','jit chain-audit lookup aggregate')
        old='case XR_DYNAMIC: j->st.exit_dynamic++; break;'
        new=(old+nl+
             '        /* '+TAG+': reasons treated exactly as the old XR_LOOKUP/XR_DYNAMIC. */'+nl+
             '        case XR_STEP_EXIT: j->st.exit_step_return++; break;'+nl+
             '        case XR_DS_GUARD: j->st.exit_ds_guard++; break;'+nl+
             '        case XR_DEAD_STUB: j->st.exit_dead_stub++; break;')
        return once(s,old,new,'jit exit switch')
    if kind=='public':
        old='uint64_t exit_dynamic, exit_native_miss, exit_direct_lookup;'
        new=(old+nl+
             '    uint64_t exit_step_return, exit_ds_guard, exit_dead_stub; /* '+TAG+' */')
        return once(s,old,new,'public stats')
    if kind=='live':
        old='    printf("[bb-jit] native-ms='
        new=('    /* '+TAG+': cumulative counters, use per-report deltas. */'+nl+
             '    printf("[bb-exit-hotspot] step-return=%llu ds-guard=%llu dead-stub=%llu normal-dynamic=%llu native-fast-miss=%llu\\n",'+nl+
             '           (unsigned long long)s->exit_step_return,'+nl+
             '           (unsigned long long)s->exit_ds_guard,'+nl+
             '           (unsigned long long)s->exit_dead_stub,'+nl+
             '           (unsigned long long)s->exit_dynamic,'+nl+
             '           (unsigned long long)s->exit_native_miss);'+nl+
             old)
        s=once(s,old,new,'live report')
        old='(s->exit_dynamic + s->exit_native_miss + s->exit_direct_lookup)'
        new='(s->exit_dynamic + s->exit_native_miss + s->exit_direct_lookup + s->exit_step_return + s->exit_ds_guard + s->exit_dead_stub)'
        s=once(s,old,new,'live total-classified includes new reasons')
        return s
    raise RuntimeError('unknown file kind '+kind)

def paths(jit_root):
    return {'backend':jit_root/'src'/'backend.h',
            'thumb':jit_root/'src'/'be_t2.c',
            'jit':jit_root/'src'/'jit.c',
            'public':jit_root/'include'/'b86.h',
            'live':ROOT/'src'/'bb_live.c'}

def plan(jit_root):
    out={}
    for kind,path in paths(jit_root).items():
        if not path.is_file(): raise RuntimeError(f'Missing source: {path}')
        before=path.read_bytes()
        s,nl,bom=decode(before)
        after=encode(edit(kind,s,nl),bom)
        backup=path.with_name(path.name+'.exit-hotspot-v1.bak')
        if backup.exists():raise RuntimeError(f'Backup exists; refusing overwrite: {backup}')
        out[kind]={'path':path,'backup':backup,'before':before,'after':after}
    return out

def probe(jit_root):
    errors=0
    for kind,path in paths(jit_root).items():
        try:
            src=path.read_bytes();s,nl,_=decode(src)
            new=edit(kind,s,nl)
            print(f'{kind:8s} READY {path} (+{len(new)-len(s)} chars)')
        except Exception as e:
            errors+=1;print(f'{kind:8s} STOP {e}')
    if errors:raise RuntimeError(f'{errors} source(s) not compatible; no changes made')

def apply(jit_root):
    if MANIFEST.exists():raise RuntimeError(f'Already applied: {MANIFEST}')
    changes=plan(jit_root) # validate ALL five before writing
    backups=[]; installed=[]
    try:
        for v in changes.values():
            v['backup'].write_bytes(v['before']);backups.append(v['backup'])
        for v in changes.values():
            v['path'].write_bytes(v['after']);installed.append(v['path'])
        manifest={kind:{'path':str(v['path']),'backup':str(v['backup']),
            'before':sha(v['before']),'after':sha(v['after'])} for kind,v in changes.items()}
        MANIFEST.write_text(json.dumps({'marker':TAG,'files':manifest},indent=2),encoding='utf-8')
    except BaseException:
        for v in changes.values():
            if v['path'] in installed:v['path'].write_bytes(v['before'])
        for v in changes.values():
            if v['backup'] in backups:v['backup'].unlink(missing_ok=True)
        raise
    print('Installed '+TAG+'; diagnostics only, all earlier edits retained.')
    verify(jit_root)

def loaded():
    if not MANIFEST.exists():raise RuntimeError('Manifest missing; run apply first')
    data=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if data.get('marker')!=TAG:raise RuntimeError('Unexpected manifest marker')
    return data['files']

def verify(jit_root):
    data=loaded();expected={k:str(p) for k,p in paths(jit_root).items()}
    for k,v in data.items():
        p=Path(v['path']);b=Path(v['backup'])
        if str(p)!=expected.get(k):raise RuntimeError(f'Unexpected source path in manifest: {p}')
        if not p.is_file() or sha(p.read_bytes())!=v['after']:raise RuntimeError(f'{k}: source changed since apply; inspect before restoring')
        if not b.is_file() or sha(b.read_bytes())!=v['before']:raise RuntimeError(f'{k}: backup changed or missing')
        print(f'{k:8s} OK {p}')
    print('Source edits verified; device performance not yet measured.')

def restore(jit_root):
    verify(jit_root) # all checks first, never silently erase later changes
    data=loaded()
    for v in data.values():Path(v['path']).write_bytes(Path(v['backup']).read_bytes())
    for v in data.values():Path(v['backup']).unlink()
    MANIFEST.unlink()
    print('Restored 5 exact originals; rebuild firmware to take effect.')

def analyze(pattern):
    import glob
    names=glob.glob(pattern)
    if not names:raise RuntimeError('No logs match '+pattern)
    import os
    names=sorted(names,key=os.path.getmtime)
    for p in names[-8:]:
        body=Path(p).read_text(encoding='utf-8',errors='replace')
        lines=[line for line in body.splitlines() if '[bb-exit-hotspot]' in line]
        if not lines:continue
        print('\nLOG',p)
        old={}
        for i,line in enumerate(lines,1):
            now={k:int(v) for k,v in re.findall(r'([a-z-]+)=(\d+)',line)}
            keys=['step-return','normal-dynamic','ds-guard','dead-stub','native-fast-miss']
            delta={k:max(0,now.get(k,0)-old.get(k,0)) for k in keys}
            total=sum(delta.values())
            print(f'report={i} '+ ' '.join(f'{k}={delta[k]}' for k in keys)+f' classified-delta={total}')
            if total:
                print('   '+ ' '.join(f'{k}={100*delta[k]/total:.1f}%' for k in keys))
            old=now

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action',choices=['probe','apply','verify','restore','analyze'])
    ap.add_argument('--blitz86',default=r'C:\blitz86_v2')
    ap.add_argument('--log',default=str(ROOT/'logs'/'bb-live-*-console.txt'))
    args=ap.parse_args()
    try:
        if args.action=='analyze':analyze(args.log)
        else:globals()[args.action](Path(args.blitz86))
    except Exception as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
