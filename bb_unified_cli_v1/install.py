#!/usr/bin/env python3
"""Guarded, reversible installer for blitzBUS bb.bat unified command interface V1.

Commands: selftest, probe, apply, verify, restore.
Preserves original root bb.bat byte-for-byte and never changes disk images/firmware.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE=Path(__file__).resolve().parent
PAYLOAD=PACKAGE/'payload'
STATE='backups/bb_unified_cli_v1_state'
TAG='BB_UNIFIED_CLI_V1'
FILES=['bb.bat','scripts/bb_cli.py']

# Baseline read from the known original bb.bat of the cleanup branch. CRLF/LF
# conversion is permitted, but changes to command semantics are refused.
ORIGINAL_BAT='''@echo off
setlocal
set CMD=%~1
if "%CMD%"=="" set CMD=run
if /I "%CMD%"=="install" (
  python "%~dp0scripts\\install_overlay.py" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="upgrade" (
  python "%~dp0scripts\\upgrade_v04.py" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="restore" (
  python "%~dp0scripts\\install_overlay.py" --restore %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="run" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\bb_run.ps1" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="build" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\bb_run.ps1" -BuildOnly
  exit /b %ERRORLEVEL%
)
echo Usage: bb.bat install ^| upgrade ^| restore ^| build ^| run [-Port COM5] [-Seconds 120] [-NoFlash]
exit /b 2
'''.encode('utf-8')


def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()


def norm(b:bytes)->bytes:
    return b.replace(b'\r\n',b'\n')


def statepath(root:Path)->Path:
    return root/STATE


def entries(root:Path):
    return [(rel,root/rel,PAYLOAD/rel) for rel in FILES]


def read_manifest(root:Path)->dict:
    return json.loads((statepath(root)/'manifest.json').read_text(encoding='utf-8'))


def probe(root:Path,verbose=True)->None:
    if statepath(root).exists():
        raise RuntimeError('Previous install state exists; use verify or restore, not apply')
    f=root/'bb.bat'
    if not f.is_file():
        raise RuntimeError(f'Original bb.bat missing: {f}')
    existing=f.read_bytes()
    if norm(existing)!=ORIGINAL_BAT:
        raise RuntimeError('bb.bat differs from expected cleanup-branch baseline (LF/CRLF allowed). Refusing overwrite.')
    if (root/'scripts/bb_cli.py').exists():
        raise RuntimeError('scripts/bb_cli.py already exists without install state; refusing overwrite')
    for _,_,p in entries(root):
        if not p.is_file():
            raise RuntimeError(f'Missing packaged payload: {p}')
    newbat=(PAYLOAD/'bb.bat').read_bytes()
    # Validate original five branches match byte-for-byte up to the additive region.
    old_prefix=ORIGINAL_BAT.split(b'echo Usage:')[0]
    if not newbat.startswith(old_prefix):
        raise RuntimeError('Payload bb.bat unexpectedly changes original legacy command branches')
    if verbose:
        print('PROBE PASS: original bb.bat matches baseline; CLI source absent; original five routes unchanged')
        print('Will modify only bb.bat and create scripts/bb_cli.py; keep full original byte backup')


def atomic_write(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.bbcli-tmp')
    if temp.exists():raise RuntimeError(f'Temporary file conflict: {temp}')
    try:
        temp.write_bytes(data)
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def apply(root:Path):
    probe(root)
    state=statepath(root)
    state.mkdir(parents=True,exist_ok=False)
    original=(root/'bb.bat').read_bytes()
    m={'tag':TAG,'files':[], 'format':1}
    try:
        state.joinpath('bb.bat.original.bin').write_bytes(original)
        for rel,path,pkg in entries(root):
            data=pkg.read_bytes()
            m['files'].append({'path':rel,'original':sha(original) if rel=='bb.bat' else None,'installed':sha(data)})
            atomic_write(path,data)
        state.joinpath('manifest.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    except BaseException:
        # Failed installs restore the original file and clean newly created files.
        atomic_write(root/'bb.bat',original)
        (root/'scripts/bb_cli.py').unlink(missing_ok=True)
        shutil.rmtree(state,ignore_errors=True)
        raise
    verify(root)
    print('APPLY PASS: unified routes installed; no build, flash, disk, or Git command executed')


def verify(root:Path):
    m=read_manifest(root)
    if m.get('tag')!=TAG or [x.get('path') for x in m.get('files',[])]!=FILES:
        raise RuntimeError('Unexpected install manifest')
    old=statepath(root)/'bb.bat.original.bin'
    oldbytes=old.read_bytes()
    if sha(oldbytes)!=m['files'][0]['original']:
        raise RuntimeError('Original bb.bat backup does not match manifest')
    for rec in m['files']:
        path=root/rec['path']
        if not path.is_file() or sha(path.read_bytes())!=rec['installed']:
            raise RuntimeError(f'Installed file changed: {path}; refusing unsafe rollback')
    print('VERIFY PASS: 2 installed files and original bb.bat backup byte-exact')


def restore(root:Path):
    verify(root)
    state=statepath(root)
    original=(state/'bb.bat.original.bin').read_bytes()
    atomic_write(root/'bb.bat',original)
    (root/'scripts/bb_cli.py').unlink()
    shutil.rmtree(state)
    print('RESTORE PASS: exact original bb.bat restored and CLI removed')


def selftest():
    for ending in ('LF','CRLF'):
        with tempfile.TemporaryDirectory(prefix='bbcli-selftest-') as d:
            root=Path(d)
            (root/'scripts').mkdir()
            old=ORIGINAL_BAT if ending=='LF' else ORIGINAL_BAT.replace(b'\n',b'\r\n')
            (root/'bb.bat').write_bytes(old)
            probe(root,False)
            apply(root)
            # Installed CLI launches its help and diagnostic without touching devices.
            cp=subprocess.run([sys.executable,str(root/'scripts/bb_cli.py'),'help'],capture_output=True,text=True)
            if cp.returncode or 'dos boot' not in cp.stdout:
                raise AssertionError('CLI help failed')
            logs=root/'logs';logs.mkdir()
            log=logs/'bb-live-20261014-193446-console.txt'
            log.write_text('[bb622-irqtrial] DELIVERED one guest IRQ0\n[bb622-watch] #1 cs:ip=0000:0000 insns=3\n')
            cp=subprocess.run([sys.executable,str(root/'scripts/bb_cli.py'),'dos','diagnose','--log',str(log)],capture_output=True,text=True)
            if cp.returncode or 'possible invalid IRQ return' not in cp.stdout:
                raise AssertionError('Log diagnostic failed')
            # Verify mutation refusal, including byte-exact original restore.
            cli=root/'scripts/bb_cli.py'
            cli.write_bytes(cli.read_bytes()+b'\nchanged')
            try:verify(root)
            except RuntimeError as e:
                if 'changed' not in str(e):raise
            else:raise AssertionError('Modified file not detected')
            cli.write_bytes((PAYLOAD/'scripts/bb_cli.py').read_bytes())
            restore(root)
            if (root/'bb.bat').read_bytes()!=old or cli.exists():
                raise AssertionError('Restore not byte-exact')
    print('SELFTEST PASS: LF+CRLF, legacy-route preservation, help, read-only diagnosis, SHA tamper detection, exact rollback')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root',type=Path,default=PACKAGE.parent)
    args=p.parse_args()
    try:
        if args.action=='selftest':selftest()
        else:globals()[args.action](args.root.resolve())
    except (OSError,RuntimeError,AssertionError,ValueError,KeyError,subprocess.SubprocessError) as e:
        print(f'ERROR [{type(e).__name__}]: {e}',file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':
    raise SystemExit(main())
