#!/usr/bin/env python3
"""Generate a separate clean-screen runner from existing blitzBUS live runner.
No Git patches, firmware modifications, source overwrites or manifest edits.
Commands: selftest, probe, apply, verify, restore.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

BASE = 'scripts/bb_live_run.ps1'
OUTPUT = 'scripts/bb_live_run_dos622.ps1'
HELPER = 'scripts/bb_dos622_screen_host.ps1'
STATE = '.bb_dos622_clean_console_state.json'
MARK = 'BB_DOS622_CLEAN_CONSOLE_HOST_V1'
LOCAL_HELPER = Path(__file__).with_name('bb_dos622_screen_host.ps1')

def sha(b): return hashlib.sha256(b).hexdigest()

def compile_runner(source: bytes) -> bytes:
    bom = source.startswith(b'\xef\xbb\xbf')
    s = source.decode('utf-8-sig')
    nl='\r\n' if '\r\n' in s else '\n'
    s = s.replace('\r\n','\n')
    if MARK in s: raise ValueError('Clean runner already generated; use ORIGINAL bb_live_run.ps1')
    a=re.compile(r'(?m)^(\s*)\[switch\]\$PhaseProfile\s*$')
    if len(a.findall(s)) != 1: raise ValueError('Cannot find unique PhaseProfile parameter declaration')
    s=a.sub(lambda m:m.group(1)+"[switch]$PhaseProfile,\n"+m.group(1)+"[ValidateSet('Screen','Events','Raw')]\n"+m.group(1)+"[string]$ConsoleView='Screen'",s)
    pat='$serial=$null'
    if s.count(pat)!=1: raise ValueError('Cannot find unique $serial initialization')
    s=s.replace(pat,"# " + MARK + " : host display only; original raw CDC log is preserved.\n"
                "if ($ConsoleView -ne 'Raw') { . (Join-Path $PSScriptRoot 'bb_dos622_screen_host.ps1') }\n"
                +pat)
    pat='            Write-Host -NoNewline $chunk'
    if s.count(pat)!=1: raise ValueError('Cannot locate unique live serial chunk output (runner changed)')
    s=s.replace(pat,"            if ($ConsoleView -eq 'Raw') { Write-Host -NoNewline $chunk }\n"
                 "            else { Write-BbDos622ConsoleChunk $chunk $ConsoleView }")
    if s.count('[System.IO.File]::AppendAllText($log,$chunk)') != 1:
        raise ValueError('Raw log preservation anchor missing; refusing transformation')
    # Flush a pending frame even if the guest goes idle after its last row update.
    cadence='        Start-Sleep -Milliseconds 15'
    if s.count(cadence) != 1: raise ValueError('Cannot locate unique live console cadence')
    s=s.replace(cadence,"        if ($ConsoleView -eq 'Screen') { Show-BbDos622HostFrame }\n"+cadence)
    return (b'\xef\xbb\xbf' if bom else b'')+s.replace('\n',nl).encode('utf-8')

def repo(args): return Path(args.root).resolve()

def files(root): return root/BASE,root/OUTPUT,root/HELPER,root/STATE

def expected(root):
    src,_,_,_=files(root)
    if not src.is_file(): raise ValueError('Missing '+str(src))
    helper=LOCAL_HELPER.read_bytes()
    return src.read_bytes(),compile_runner(src.read_bytes()),helper

def probe(root):
    orig,edited,helper=expected(root)
    src,out,helpdst,st=files(root)
    if st.exists(): raise ValueError('State already exists; run verify or restore')
    for p in (out,helpdst):
        if p.exists(): raise ValueError('Destination already exists; refusing overwrite: '+str(p))
    print(f'PROBE PASS: original untouched {src} ({len(orig)} bytes, SHA {sha(orig)[:12]}); generated output {len(edited)} bytes')
    return orig,edited,helper

def apply(root):
    orig,edited,helper=probe(root)
    src,out,helpdst,st=files(root)
    try:
        out.write_bytes(edited)
        helpdst.write_bytes(helper)
        st.write_text(json.dumps({'version':MARK,'input_sha256':sha(orig),'output_sha256':sha(edited),
                                 'helper_sha256':sha(helper)},indent=2)+'\n',encoding='utf8')
        verify(root)
    except Exception:
        # Only remove files created here. Never modify user's original runner.
        for p in (st,helpdst,out):
            if p.is_file(): p.unlink()
        raise
    print('APPLIED: separate clean MS-DOS console runner, all raw diagnostics still logged; original source unchanged')

def verify(root):
    src,out,helpdst,st=files(root)
    if not st.is_file(): raise ValueError('Missing state: '+str(st))
    m=json.loads(st.read_text(encoding='utf8'))
    orig,edited,helper=expected(root)
    checks=((src,m['input_sha256'],orig),(out,m['output_sha256'],edited),(helpdst,m['helper_sha256'],helper))
    for p,h,data in checks:
        if not p.is_file() or sha(p.read_bytes())!=h or p.read_bytes()!=data:
            raise ValueError('Changed or missing file: '+str(p))
    print('VERIFY PASS: original runner, generated clean runner and helper all SHA-verified')

def restore(root):
    verify(root)
    _,out,helpdst,st=files(root)
    for p in (st,helpdst,out): p.unlink()
    print('RESTORED: generated files removed; original runner was never modified')

def selftest():
    mock=("[CmdletBinding()]\nparam(\n    [switch]$PhaseProfile\n)\n"
          "$serial=$null\ntry {\n $chunk=$serial.ReadExisting()\n if($chunk){\n"
          "            Write-Host -NoNewline $chunk\n"
          "            [System.IO.File]::AppendAllText($log,$chunk)\n }\n        Start-Sleep -Milliseconds 15\n}\n")
    for eol in ('\n','\r\n'):
        with TemporaryDirectory() as td:
            root=Path(td);(root/'scripts').mkdir()
            (root/BASE).write_bytes(mock.replace('\n',eol).encode('utf8'))
            stage=compile_runner((root/BASE).read_bytes())
            assert stage.count(MARK.encode())==1
            assert b'[System.IO.File]::AppendAllText($log,$chunk)' in stage
            assert b'$ConsoleView' in stage and b'Write-BbDos622ConsoleChunk' in stage
            assert b'Write-Host -NoNewline $chunk }' in stage
            assert (root/BASE).read_bytes()==mock.replace('\n',eol).encode('utf8')
            probe(root);apply(root);verify(root);restore(root)
            assert not (root/OUTPUT).exists() and not (root/HELPER).exists()
            assert (root/BASE).read_bytes()==mock.replace('\n',eol).encode('utf8')
    print('SELFTEST PASS: LF/CRLF, stable anchors, raw logging retained, SHA verification, exact generated-file rollback')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    p.add_argument('--root',default='.')
    a=p.parse_args()
    try:
        if a.action=='selftest':selftest()
        elif a.action=='probe':probe(repo(a))
        elif a.action=='apply':apply(repo(a))
        elif a.action=='verify':verify(repo(a))
        elif a.action=='restore':restore(repo(a))
    except (OSError,ValueError,AssertionError,KeyError) as exc:
        p.exit(1,'ERROR: '+str(exc)+'\n')
