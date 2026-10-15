#!/usr/bin/env python3
"""Guarded upgrade from installed dual console V1 -> V2 editable VGA keyboard.

Only edits V1 launcher and its own V1 manifest so that V1's hash verifier
continues to pass. Original DOS/IRQ0 runner + C color module stay untouched.
V2 adds two scripts (launcher and color keyboard); per-run throwaway PS runner
is generated from the protected original by the V2 launcher.

Actions: selftest, probe, apply, verify, restore
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

HERE=Path(__file__).resolve().parent
TAG='BB_DUAL_INPUT_V2'
V1_STATE=Path('backups/bb_dos_dual_console_v1_state/manifest.json')
V2_STATE=Path('backups/bb_dos_dual_input_v2_state')
LAUNCHER=Path('scripts/bb_dos_dual_launch.py')
NEW_LAUNCHER=Path('scripts/bb_dos_dual_launch_v2.py')
NEW_VIEWER=Path('scripts/bb622_color_keyboard_v2.ps1')
PROTECTED=Path('scripts/bb_live_run_dos622_irqtrial.ps1')
COLOR=Path('scripts/bb622_descent_color_host.ps1')
CLI=Path('scripts/bb_cli.py')

OLD='sys.exit(run(sys.argv[1:]))'
NEW="sys.exit(subprocess.call([sys.executable, str(ROOT / 'scripts' / 'bb_dos_dual_launch_v2.py'), *sys.argv[1:]], cwd=str(ROOT)))  # BB_DUAL_INPUT_V2"

def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def atomic(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.bbdual2-',suffix='.tmp',delete=False) as f:
        p=Path(f.name)
        f.write(blob)
    try: os.replace(p,path)
    finally:
        if p.exists():p.unlink()


def patch_launcher(blob:bytes)->bytes:
    eol=b'\r\n' if b'\r\n' in blob else b'\n'
    raw=blob.replace(b'\r\n',b'\n')
    if raw.count(OLD.encode())!=1 or TAG.encode() in raw:
        raise ValueError('V1 launcher exact anchor mismatch or already upgraded; no changes')
    raw=raw.replace(OLD.encode(),NEW.encode(),1)
    return raw.replace(b'\n',eol)


def context(root:Path):
    paths=[V1_STATE, LAUNCHER,CLI,PROTECTED,COLOR]
    for rel in paths:
        if not (root/rel).is_file():raise ValueError(f'Missing V1 prerequisite: {rel}')
    obj=json.loads((root/V1_STATE).read_bytes())
    if obj.get('tag')!='BB_DOS_DUAL_CONSOLE_V1':raise ValueError('Unexpected V1 state tag')
    old=(root/LAUNCHER).read_bytes()
    if digest(old)!=obj['launcher_sha']:raise ValueError('V1 launcher hash mismatch; do not overwrite local edits')
    if digest((root/CLI).read_bytes())!=obj['cli_installed']:raise ValueError('V1 CLI hash mismatch')
    if digest((root/PROTECTED).read_bytes())!=obj['protected_runner_sha']:raise ValueError('Protected DOS runner changed from V1 baseline')
    return old,patch_launcher(old),(root/V1_STATE).read_bytes(),obj


def read_state(root:Path):
    p=root/V2_STATE/'manifest.json'
    if not p.is_file():raise ValueError(f'V2 backup missing: {p}')
    obj=json.loads(p.read_bytes())
    if obj.get('tag')!=TAG:raise ValueError('V2 tag mismatch')
    return obj


def verify(root:Path):
    obj=read_state(root)
    state=root/V2_STATE
    for rel, expected in ((LAUNCHER,obj['launcher_new']),
                         (NEW_LAUNCHER,obj['new_launcher']),
                         (NEW_VIEWER,obj['new_viewer']),
                         (V1_STATE,obj['v1_manifest_new']),
                         (PROTECTED,obj['protected_sha'])):
        if not (root/rel).is_file() or digest((root/rel).read_bytes())!=expected:
            raise ValueError(f'V2 installation verification failed: {rel}')
    for name,expected in (('v1_launcher_original.bin',obj['launcher_old']),
                          ('v1_manifest_original.json',obj['v1_manifest_old'])):
        if digest((state/name).read_bytes())!=expected:raise ValueError('V2 rollback backup corrupted: '+name)
    v1=json.loads((root/V1_STATE).read_bytes())
    if v1['launcher_sha']!=obj['launcher_new']:
        raise ValueError('V1 launcher verifier not updated with V2 installed hash')
    print('VERIFY PASS: V2 window and keyboard installed; V1 SHA verifier still valid; DOS runner untouched')


def probe(root:Path):
    if (root/V2_STATE/'manifest.json').exists():
        verify(root);print('ALREADY INSTALLED');return
    if (root/V2_STATE).exists():
        raise ValueError('Partial V2 state: inspect before retrying (nothing deleted)')
    for rel in (NEW_LAUNCHER,NEW_VIEWER):
        if (root/rel).exists(): raise ValueError(f'V2 target already exists, refusing overwrite: {rel}')
    old,new,raw,v1=context(root)
    print('PROBE PASS: V1 launcher exact guarded entrypoint available')
    print('Original V1 launcher:',digest(old))
    print('Upgrade V2 launcher: ',digest(new))
    print('V1 baseline verified; protected DOS runner, renderer, CLI, images not modified')


def apply(root:Path):
    if (root/V2_STATE/'manifest.json').exists():
        verify(root);print('ALREADY INSTALLED');return
    probe(root)
    old,new,v1raw,v1=context(root)
    newv1=dict(v1,launcher_sha=digest(new))
    # Retain all existing metadata and preserve the old manifest byte exact
    # in V2 rollback before changing this one V1 hash.
    newv1raw=(json.dumps(newv1,indent=2)+'\n').encode()
    blobs={NEW_LAUNCHER:(HERE/NEW_LAUNCHER).read_bytes(),NEW_VIEWER:(HERE/NEW_VIEWER).read_bytes()}
    man={'tag':TAG,'launcher_old':digest(old),'launcher_new':digest(new),
         'v1_manifest_old':digest(v1raw),'v1_manifest_new':digest(newv1raw),
         'new_launcher':digest(blobs[NEW_LAUNCHER]),'new_viewer':digest(blobs[NEW_VIEWER]),
         'protected_sha':digest((root/PROTECTED).read_bytes())}
    state=root/V2_STATE
    state.mkdir(parents=True)
    created=[]
    try:
        atomic(state/'v1_launcher_original.bin',old)
        atomic(state/'v1_manifest_original.json',v1raw)
        for rel,blob in blobs.items():
            if (root/rel).exists():raise ValueError('Unexpected file collision: '+str(rel))
            atomic(root/rel,blob);created.append(rel)
        if (root/LAUNCHER).read_bytes()!=old or (root/V1_STATE).read_bytes()!=v1raw:
            raise ValueError('V1 modified during V2 install; refusing overwrite')
        atomic(root/LAUNCHER,new)
        atomic(root/V1_STATE,newv1raw)
        atomic(state/'manifest.json',(json.dumps(man,indent=2)+'\n').encode())
        verify(root)
    except Exception:
        if (root/LAUNCHER).exists() and digest((root/LAUNCHER).read_bytes())==digest(new):atomic(root/LAUNCHER,old)
        if (root/V1_STATE).exists() and digest((root/V1_STATE).read_bytes())==digest(newv1raw):atomic(root/V1_STATE,v1raw)
        for rel in created:
            if (root/rel).is_file() and digest((root/rel).read_bytes())==digest(blobs[rel]): (root/rel).unlink()
        # Preserve partial backup, never delete user data.
        raise
    print('APPLY PASS: bb.bat dos boot opens VGA color terminal WITH keyboard/input strip + raw logging terminal')
    print('No DOS firmware or media changed. F2 switches LINE/LIVE. Ctrl+X quits from color terminal.')


def restore(root:Path):
    verify(root)
    state=root/V2_STATE
    original=(state/'v1_launcher_original.bin').read_bytes()
    prev_manifest=(state/'v1_manifest_original.json').read_bytes()
    atomic(root/LAUNCHER,original)
    atomic(root/V1_STATE,prev_manifest)
    for rel in (NEW_LAUNCHER,NEW_VIEWER): (root/rel).unlink()
    for name in ('manifest.json','v1_launcher_original.bin','v1_manifest_original.json'):(state/name).unlink()
    state.rmdir()
    print('RESTORE PASS: V1 launcher and V1 manifest restored byte-exact; DOS runner unchanged')


def selftest():
    # Simulate a complete V1 installation and a reversible V2 upgrade.
    original=(Path(__file__).parents[1]/'BLITZBUS_DOS_DUAL_CONSOLE_V1/scripts/bb_dos_dual_launch.py')
    if not original.is_file(): original=None
    fixture=(original.read_bytes() if original else
        b'import sys\nimport subprocess\nfrom pathlib import Path\nROOT=Path(__file__).parent\nif __name__ == "__main__":\n    try:\n        sys.exit(run(sys.argv[1:]))\n    except Exception: pass\n')
    for eol in (b'\n',b'\r\n'):
        src=fixture.replace(b'\r\n',b'\n').replace(b'\n',eol)
        out=patch_launcher(src)
        assert out.count(TAG.encode())==1 and out!=src
        if eol==b'\r\n': assert out.count(b'\n')==out.count(b'\r\n')
        try:patch_launcher(out);raise AssertionError('Double patch accepted')
        except ValueError:pass
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for f,b in [(LAUNCHER,src),(CLI,b'TEST CLI'),(PROTECTED,b'TEST protected runner'),(COLOR,b'TEST color module')]:
                p=root/f;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
            p=root/V1_STATE;p.parent.mkdir(parents=True,exist_ok=True)
            obj={'tag':'BB_DOS_DUAL_CONSOLE_V1','launcher_sha':digest(src),
                 'cli_installed':digest(b'TEST CLI'),'protected_runner_sha':digest(b'TEST protected runner')}
            v1=(json.dumps(obj,indent=2)+'\n').encode();p.write_bytes(v1)
            probe(root);apply(root);verify(root)
            assert digest((root/PROTECTED).read_bytes())==digest(b'TEST protected runner')
            restore(root)
            assert (root/LAUNCHER).read_bytes()==src and (root/V1_STATE).read_bytes()==v1
    from subprocess import run as p_run
    check=p_run([sys.executable,'-m','py_compile',str(HERE/NEW_LAUNCHER)],capture_output=True,text=True)
    if check.returncode:raise RuntimeError(check.stderr)
    py=(HERE/NEW_LAUNCHER).read_text()
    ps=(HERE/NEW_VIEWER).read_text()
    assert 'PROTECTED.read_bytes()' in py and 'BB_DUAL_V2_INPUT_DIR' in py
    assert 'SerialPort' not in ps and 'Send-BbV2Event' in ps
    # Verify the generated per-run runner preserves the original bytes
    # except for replacing exactly one keyboard-read anchor.
    import importlib.util
    spec=importlib.util.spec_from_file_location('bb_dual_launcher_v2_test',HERE/NEW_LAUNCHER)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for newline in (b'\n',b'\r\n'):
        original=b'\xef\xbb\xbf'+(b'header\n'+module.ANCHOR.encode()+b'\nfooter\n').replace(b'\n',newline)
        patched=module.patched_runner(original)
        assert patched.startswith(b'\xef\xbb\xbf') and TAG.encode() in patched
        assert patched.endswith(b'footer'+newline)
        assert b'BB_DUAL_V2_INPUT_DIR' in patched
        try:module.patched_runner(patched);raise AssertionError('Double keyboard patch accepted')
        except RuntimeError:pass
    print('SELFTEST PASS: upgrade/verify/restore, 2 line endings, SHA lineage V1 preserved, source runner untouched')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    ap.add_argument('--root',type=Path,default=HERE.parent)
    args=ap.parse_args()
    try:
        globals()[args.action](args.root) if args.action != 'selftest' else selftest()
        return 0
    except (OSError,ValueError,RuntimeError,AssertionError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
