#!/usr/bin/env python3
"""Guarded V2 keyboard COM5 forwarding fix.

No DOS firmware, disk image, original runner, color-renderer, or V1 launcher edits.
Only updates two owned V2 scripts + the installed V2 SHA manifest; full rollback.
Commands: selftest, probe, apply, verify, restore.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TAG = 'BB_DUAL_INPUT_V2_FIX1'
STATE = Path('backups/bb_dos_dual_input_v2_fix1_state')
V2STATE = Path('backups/bb_dos_dual_input_v2_state/manifest.json')
V1STATE = Path('backups/bb_dos_dual_console_v1_state/manifest.json')
LAUNCH = Path('scripts/bb_dos_dual_launch_v2.py')
VIEW = Path('scripts/bb622_color_keyboard_v2.ps1')
PROTECTED = Path('scripts/bb_live_run_dos622_irqtrial.ps1')


def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


def atomic(p: Path, b: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(prefix='.bbdualfix1-',suffix='.tmp',dir=p.parent,delete=False) as f:
        tmp=Path(f.name)
        f.write(b)
    try: os.replace(tmp,p)
    finally:
        if tmp.exists():tmp.unlink()


def prerequisites(root: Path):
    for rel in (LAUNCH,VIEW,V2STATE,PROTECTED,V1STATE):
        if not (root/rel).is_file():raise RuntimeError('Required installed V2 file missing: '+str(rel))
    oldv2raw=(root/V2STATE).read_bytes()
    meta=json.loads(oldv2raw)
    if meta.get('tag')!='BB_DUAL_INPUT_V2':raise RuntimeError('Unexpected V2 manifest tag')
    oldlaunch=(root/LAUNCH).read_bytes()
    oldview=(root/VIEW).read_bytes()
    if sha(oldlaunch)!=meta['new_launcher'] or sha(oldview)!=meta['new_viewer']:
        raise RuntimeError('Installed V2 scripts differ from recorded SHA; refusing overwrite')
    if sha((root/PROTECTED).read_bytes())!=meta['protected_sha']:
        raise RuntimeError('Protected runner changed since V2: refusing update')
    oldv1=json.loads((root/V1STATE).read_bytes())
    v1launch=root/'scripts/bb_dos_dual_launch.py'
    if sha(v1launch.read_bytes())!=oldv1['launcher_sha']:
        raise RuntimeError('V1 launcher does not match existing protected lineage')
    return oldv2raw,meta,oldlaunch,oldview


def state(root: Path):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise RuntimeError('FIX1 manifest not installed: '+str(p))
    x=json.loads(p.read_bytes())
    if x.get('tag')!=TAG:raise RuntimeError('FIX1 manifest tag mismatch')
    return x


def verify(root: Path):
    m=state(root)
    oldv2raw=(root/STATE/'v2_manifest_before.json').read_bytes()
    oldlaunch=(root/STATE/'launcher_v2_before.py').read_bytes()
    oldview=(root/STATE/'viewer_v2_before.ps1').read_bytes()
    if sha(oldv2raw)!=m['original']['v2'] or sha(oldlaunch)!=m['original']['launcher'] or sha(oldview)!=m['original']['viewer']:
        raise RuntimeError('Original V2 rollback bytes do not match manifest')
    checks={LAUNCH:m['installed']['launcher'],VIEW:m['installed']['viewer'],V2STATE:m['installed']['v2'],PROTECTED:m['protected_sha']}
    for rel,digest in checks.items():
        if sha((root/rel).read_bytes())!=digest:raise RuntimeError('Installed FIX1 content mismatch: '+str(rel))
    v2=json.loads((root/V2STATE).read_bytes())
    if v2.get('new_launcher')!=m['installed']['launcher'] or v2.get('new_viewer')!=m['installed']['viewer']:
        raise RuntimeError('V2 SHA lineage no longer matches FIX1 scripts')
    v1=json.loads((root/V1STATE).read_bytes())
    if sha((root/'scripts/bb_dos_dual_launch.py').read_bytes())!=v1['launcher_sha']:
        raise RuntimeError('V1 launcher changed')
    print('VERIFY PASS: V2 keyboard COM5 owner ACK fix; V1/V2 lineage valid; DOS runner unchanged')


def probe(root: Path):
    if (root/STATE/'manifest.json').is_file():
        verify(root)
        print('ALREADY INSTALLED')
        return
    if (root/STATE).exists():raise RuntimeError('Partial FIX1 state folder; inspect rather than overwrite')
    oldv2raw,meta,oldlaunch,oldview=prerequisites(root)
    fixlaunch=(HERE/LAUNCH).read_bytes();fixview=(HERE/VIEW).read_bytes()
    if sha(oldlaunch)==sha(fixlaunch) or sha(oldview)==sha(fixview):
        raise RuntimeError('Fix already partially applied; refusing automatic overwrite')
    if b'BB_DUAL_INPUT_V2_FIX1' not in fixlaunch or b'QUEUED' not in fixview or b'Read-BbV2OwnerAck' not in fixview:
        raise RuntimeError('Package contents incomplete')
    print('PROBE PASS: V2 scripts match installed SHA values; FIX1 can be applied safely')
    print('V2 launcher sha256:',sha(oldlaunch))
    print('V2 color window sha256:',sha(oldview))
    print('Only two V2 scripts and V2 SHA metadata will change; original DOS/IRQ0 runner untouched')


def apply(root: Path):
    if (root/STATE/'manifest.json').is_file():
        verify(root);print('ALREADY INSTALLED');return
    probe(root)
    oldv2raw,meta,oldlaunch,oldview=prerequisites(root)
    fixlaunch=(HERE/LAUNCH).read_bytes();fixview=(HERE/VIEW).read_bytes()
    nextmeta=dict(meta,new_launcher=sha(fixlaunch),new_viewer=sha(fixview))
    newv2raw=(json.dumps(nextmeta,indent=2)+'\n').encode()
    man={ 'tag':TAG, 'original':{'v2':sha(oldv2raw),'launcher':sha(oldlaunch),'viewer':sha(oldview)},
          'installed':{'v2':sha(newv2raw),'launcher':sha(fixlaunch),'viewer':sha(fixview)},
          'protected_sha':sha((root/PROTECTED).read_bytes()) }
    d=root/STATE
    d.mkdir(parents=True)
    try:
        atomic(d/'v2_manifest_before.json',oldv2raw)
        atomic(d/'launcher_v2_before.py',oldlaunch)
        atomic(d/'viewer_v2_before.ps1',oldview)
        for rel,b,old in ((LAUNCH,fixlaunch,oldlaunch),(VIEW,fixview,oldview),(V2STATE,newv2raw,oldv2raw)):
            if (root/rel).read_bytes()!=old:raise RuntimeError('Concurrent modification: '+str(rel))
            atomic(root/rel,b)
        atomic(d/'manifest.json',(json.dumps(man,indent=2)+'\n').encode())
        verify(root)
    except BaseException:
        # If any source still equals our expected new hash, restore only that source.
        for rel,new,old in ((LAUNCH,fixlaunch,oldlaunch),(VIEW,fixview,oldview),(V2STATE,newv2raw,oldv2raw)):
            if (root/rel).is_file() and sha((root/rel).read_bytes())==sha(new):atomic(root/rel,old)
        # Preserve the backup state for inspection rather than deleting it.
        raise
    print('APPLY PASS: buffered commands now require COM5-owner ACK before status shows forwarded')
    print('No firmware, SD media, code in the protected runner or V1 launcher changed')


def restore(root: Path):
    verify(root)
    d=root/STATE
    original=((V2STATE,'v2_manifest_before.json'),(LAUNCH,'launcher_v2_before.py'),(VIEW,'viewer_v2_before.ps1'))
    for rel,name in original:atomic(root/rel,(d/name).read_bytes())
    for name in ('manifest.json','v2_manifest_before.json','launcher_v2_before.py','viewer_v2_before.ps1'):
        (d/name).unlink()
    d.rmdir()
    print('RESTORE PASS: installed V2 scripts and V2 manifest restored byte-exact')


def selftest():
    # Validate exact-size event protocol parsing, mode and single COM writer.
    launcher=(HERE/LAUNCH).read_text(encoding='utf8')
    view=(HERE/VIEW).read_text(encoding='utf8')
    assert 'BB_DUAL_INPUT_V2_FIX1' in launcher and "owner_ack.txt" in launcher
    assert '$serial.Write([string][char]$bbV2Char)' in launcher
    assert '$serial.Write("`r")' in launcher
    assert 'Read-BbV2OwnerAck' in view
    assert 'QUEUED' in view and 'FORWARDED to COM5' in view
    assert 'System.IO.Ports.SerialPort' not in view and '$serial.Write' not in view
    assert "Get-ChildItem -LiteralPath $env:BB_DUAL_V2_INPUT_DIR" in launcher
    spec=importlib.util.spec_from_file_location('bb_dos_dual_launch_v2_fix1',HERE/LAUNCH)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    for eol in (b'\n',b'\r\n'):
        original=b'\xef\xbb\xbf'+(b'HEADER\n'+mod.ANCHOR.encode()+b'\nEND\n').replace(b'\n',eol)
        generated=mod.patched_runner(original)
        assert generated.startswith(b'\xef\xbb\xbf')
        assert b'BB_DUAL_INPUT_V2_FIX1' in generated
        assert generated.count(b'owner_ack.txt')==1
        assert b'if($bbV2HaveKey){' in generated
        assert generated.endswith(b'END'+eol)
        try:mod.patched_runner(generated);raise AssertionError('double patch permitted')
        except RuntimeError:pass
    assert subprocess.call([sys.executable,'-m','py_compile',str(HERE/LAUNCH)])==0
    with tempfile.TemporaryDirectory() as t:
        root=Path(t)
        oldpkg=HERE.parent/'BLITZBUS_DOS_DUAL_INPUT_V2'
        v2launch=(oldpkg/LAUNCH).read_bytes() if (oldpkg/LAUNCH).is_file() else b'V2 launcher fixture'
        v2view=(oldpkg/VIEW).read_bytes() if (oldpkg/VIEW).is_file() else b'V2 viewer fixture'
        protected=b'Original read-only IRQ0 DOS runner'
        cli=b'V1 CLI unchanged'
        v1launcher=b'V1 launcher unchanged'
        for rel,data in ((LAUNCH,v2launch),(VIEW,v2view),(PROTECTED,protected),
                         (Path('scripts/bb_dos_dual_launch.py'),v1launcher)):
            p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        v2={'tag':'BB_DUAL_INPUT_V2','new_launcher':sha(v2launch),'new_viewer':sha(v2view),'protected_sha':sha(protected)}
        p=root/V2STATE;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((json.dumps(v2)+'\n').encode())
        v1={'tag':'BB_DOS_DUAL_CONSOLE_V1','launcher_sha':sha(v1launcher)}
        p=root/V1STATE;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((json.dumps(v1)+'\n').encode())
        probe(root);apply(root);verify(root);restore(root)
        assert (root/LAUNCH).read_bytes()==v2launch and (root/VIEW).read_bytes()==v2view
        assert (root/V2STATE).read_bytes()==(json.dumps(v2)+'\n').encode()
        assert (root/PROTECTED).read_bytes()==protected
    print('SELFTEST PASS: guarded V2 to FIX1 and rollback; event protocol; owner ACK; no DOS source changes')


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    ap.add_argument('--root',type=Path,default=ROOT)
    args=ap.parse_args(argv)
    try:
        globals()[args.action](args.root) if args.action != 'selftest' else selftest()
        return 0
    except Exception as ex:
        print('ERROR:',ex,file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
