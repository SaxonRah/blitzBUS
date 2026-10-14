#!/usr/bin/env python3
"""Host-only PIC probe control for blitzBUS DOS622 Descent runner.

Commands: selftest/probe/apply/verify/restore/status. Reversible, no edits to existing runner.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, tempfile, sys
from pathlib import Path

TAG='BB622_PIC_HOST_CONTROL_V1'
STATE='.bb622_pic_host_control_v1_state'
ROOT=Path(__file__).resolve().parent
BASE='scripts/bb_live_run_dos622_descent.ps1'
NEW='scripts/bb_live_run_dos622_pic_control.ps1'
REQUEST='scripts/bb622_pic_toggle.ps1'
DESCMAN='.bb622_descent_swap_v1_state/manifest.json'
SRC='src/bb_live.c'
PIC='BB622_PIC_PENDING_V1'
SIGNATURE='BB622_PIC_HOST_CONTROL_V1'
SHA=lambda b:hashlib.sha256(b).hexdigest()

def split(raw):
    bom=b''
    if raw.startswith(b'\xef\xbb\xbf'):
        bom,raw=raw[:3],raw[3:]
    encoding='utf-8'
    s=raw.decode(encoding)
    e='\r\n' if '\r\n' in s else '\n'
    if e=='\r\n' and s.replace('\r\n','').find('\n')>=0:
        raise ValueError('Mixed line endings refused')
    return s.replace('\r\n','\n'),e,bom

def pack(s,e,bom):return bom+s.replace('\n',e).encode('utf-8')

INJECT=r"""        # BB622_PIC_HOST_CONTROL_V1: service independent PIC-probe toggle request.
        # Exactly one requester is allowed; firmware sends [bb622-picprobe] ACK.
        if ([System.IO.File]::Exists($bbPicToggleRequest)) {
            try {
                $bbPicText=[System.IO.File]::ReadAllText($bbPicToggleRequest).Trim().ToUpperInvariant()
                if ($bbPicText -eq 'Y') {
                    [System.IO.File]::Delete($bbPicToggleRequest)
                    $serial.Write([string][char]0x19)
                    [System.IO.File]::AppendAllText($log,"[bb622-piccontrol] SENT Ctrl+Y 0x19 awaiting firmware ACK`n")
                } else {
                    [System.IO.File]::Delete($bbPicToggleRequest)
                    [System.IO.File]::AppendAllText($log,"[bb622-piccontrol] REJECT invalid request`n")
                }
            } catch {
                [System.IO.File]::AppendAllText($log,"[bb622-piccontrol] ERROR $($_.Exception.Message)`n")
            }
        }
"""

REQUESTER=r"""[CmdletBinding()]
param([ValidateRange(2,60)][int]$TimeoutSeconds=15)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dir=Join-Path $root 'logs'
$req=Join-Path $dir 'bb622-picprobe.request'
if ([System.IO.File]::Exists($req)) {throw "PIC control request already pending: $req"}
$source=Join-Path $root 'src\bb_live.c'
if(!(Test-Path -LiteralPath $source)) {throw 'Missing firmware source'}
if(-not ([System.IO.File]::ReadAllText($source).Contains('BB622_PIC_PENDING_V1'))) {
    throw 'PIC pending firmware patch is NOT installed in source. Install and flash it first.'
}
$log=Get-ChildItem -LiteralPath $dir -Filter 'bb-live-*-console.txt' -File |
 Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(!$log) {throw 'No raw console capture found; run the PIC-control console first'}
$start=[System.IO.FileInfo]::new($log.FullName).Length
$age=([datetime]::UtcNow-$log.LastWriteTimeUtc).TotalSeconds
if($age -gt 12) {Write-Warning "Newest raw log was last updated $([int]$age)s ago. Confirm the PIC-control runner is open."}
$tmp=$req+'.new.'+[guid]::NewGuid().ToString('N')
try {
 [System.IO.File]::WriteAllText($tmp,'Y',[System.Text.Encoding]::ASCII)
 [System.IO.File]::Move($tmp,$req)
} finally { if([System.IO.File]::Exists($tmp)){[System.IO.File]::Delete($tmp)} }
Write-Host 'Requested PIC Ctrl+Y toggle. Waiting for host SENT and Pico ACK...'
$deadline=[datetime]::UtcNow.AddSeconds($TimeoutSeconds)
$hostSent=$false
while([datetime]::UtcNow -lt $deadline) {
 Start-Sleep -Milliseconds 120
 try {
  $f=[System.IO.File]::Open($log.FullName,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
  try {
   if($f.Length -gt $start){
    [void]$f.Seek($start,[System.IO.SeekOrigin]::Begin)
    $r=[System.IO.StreamReader]::new($f,[System.Text.Encoding]::UTF8,$true,4096,$true)
    try { $new=$r.ReadToEnd() } finally { $r.Dispose() }
    if($new.Contains('[bb622-piccontrol] SENT Ctrl+Y')){$hostSent=$true}
    if($new -match '(?m)^\[bb622-picprobe\] Ctrl\+Y (ON|OFF) pending-only[^\r\n]*') {
     Write-Host "PICO ACK: $($Matches[0])" -ForegroundColor Green
     exit 0
    }
    if($new.Contains('[bb622-piccontrol] REJECT') -or $new.Contains('[bb622-piccontrol] ERROR')) {
     Write-Host 'HOST ERROR processing request; check raw log' -ForegroundColor Red
     exit 2
    }
   }
  } finally {$f.Dispose()}
 } catch { }
}
# Prevent stale future toggles if main runner wasn't alive.
if([System.IO.File]::Exists($req)){
 try { if([System.IO.File]::ReadAllText($req).Trim() -eq 'Y') {[System.IO.File]::Delete($req)} } catch {}
}
if($hostSent) {Write-Host 'HOST SENT but PICO NO ACK. Firmware may be old, Ctrl+Y unhandled, or serial output missing.' -ForegroundColor Red}
else {Write-Host 'HOST DID NOT SEND. Wrong runner/no live runner/request polling not active.' -ForegroundColor Red}
Write-Host "Raw log: $($log.FullName)"
exit 3
"""

def transform(raw):
    s,e,bom=split(raw)
    if TAG in s:raise ValueError('Runner already modified')
    if 'BB622_DESCENT_SWAP_V1' not in s:
        raise ValueError('Expected Descent V1 host runner not found')
    anchor="$logs=Join-Path $root 'logs'"
    if s.count(anchor)!=1:raise ValueError('Runner log path not unique')
    s=s.replace(anchor,anchor+"\n$bbPicToggleRequest=Join-Path $logs 'bb622-picprobe.request'",1)
    sleep='        Start-Sleep -Milliseconds 15'
    if s.count(sleep)!=1:raise ValueError('Runner input-loop 15 ms sleep not unique')
    s=s.replace(sleep,INJECT+sleep,1)
    return pack(s,e,bom)

def precheck(root):
    base=root/BASE
    if not base.is_file():raise ValueError('Missing Descent console runner: '+BASE)
    m=root/DESCMAN
    if not m.is_file():raise ValueError('Missing Descent swap install state: '+DESCMAN)
    obj=json.loads(m.read_bytes())
    if obj.get('tag')!='BB622_DESCENT_SWAP_V1':raise ValueError('Unexpected Descent state tag')
    row=next((r for r in obj.get('files',[]) if r.get('path')==BASE),None)
    if not row or SHA(base.read_bytes())!=row.get('installed'):
        raise ValueError('Descent host runner differs from installed SHA. No changes made.')
    return transform(base.read_bytes())

def check_firmware(root,printout=True):
    source=root/SRC
    ok=source.is_file() and PIC.encode() in source.read_bytes()
    fw=Path(r'C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.uf2')
    if os.name!='nt':fw=Path('/nonexistent/uf2')
    in_fw=fw.is_file() and b'[bb622-picprobe]' in fw.read_bytes()
    if printout:
        print('PIC SOURCE: '+('marker found' if ok else 'NOT installed'))
        print('COMPILED UF2: '+ ('PIC string found' if in_fw else ('marker not found in raw UF2 (inconclusive)' if fw.is_file() else 'not found')))
        print('NOTE: UF2 inspection does not prove that the Pico was flashed with this binary.')
    return ok

def preview(root=ROOT):
    if (root/STATE).exists():raise ValueError('Already installed; use verify/status/restore')
    if (root/NEW).exists() or (root/REQUEST).exists():raise ValueError('Output already exists; not overwriting')
    a=precheck(root)
    print('PROBE PASS: Descent runner checksum matches; generating two host files only')
    check_firmware(root)
    return a

def write_atomic(p, b):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.bb622picnew')
    try: t.write_bytes(b);os.replace(t,p)
    finally:t.unlink(missing_ok=True)

def verify(root=ROOT):
    mp=root/STATE/'manifest.json'
    if not mp.is_file():raise ValueError('No host control install state')
    obj=json.loads(mp.read_bytes())
    if obj.get('tag')!=TAG:raise ValueError('Wrong install state')
    if SHA((root/BASE).read_bytes())!=obj['base_sha']:
        raise ValueError('Source runner changed from recorded SHA')
    for rel,expected in obj['outputs'].items():
        if not (root/rel).is_file() or SHA((root/rel).read_bytes())!=expected:
            raise ValueError('Generated file changed/missing: '+rel)
    print('VERIFY PASS: source runner intact and two host outputs match SHA')

def apply(root=ROOT):
    data=preview(root)
    products={NEW:data,REQUEST:REQUESTER.encode('utf-8')}
    state=root/STATE;state.mkdir()
    try:
        for rel,b in products.items():write_atomic(root/rel,b)
        m=dict(tag=TAG,base_sha=SHA((root/BASE).read_bytes()),outputs={p:SHA(b) for p,b in products.items()})
        write_atomic(state/'manifest.json',(json.dumps(m,indent=2)+'\n').encode())
        verify(root)
    except BaseException:
        for rel in products:(root/rel).unlink(missing_ok=True)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: two HOST-ONLY files; firmware, SHA lineage and SD images untouched.')

def restore(root=ROOT):
    verify(root)
    obj=json.loads((root/STATE/'manifest.json').read_bytes())
    for rel in obj['outputs']:(root/rel).unlink()
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: two host files deleted; source unchanged.')

def selftest():
    for e in ('\n','\r\n'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            base="""[CmdletBinding()]
param([switch]$NoFlash)
$root='C:\\blitzBUS'
$logs=Join-Path $root 'logs'
# BB622_DESCENT_SWAP_V1
$serial=$null
try {
  while ($true) {
        $chunk=$serial.ReadExisting()
        if($chunk){[System.IO.File]::AppendAllText($log,$chunk)}
        Start-Sleep -Milliseconds 15
  }
} finally {$serial.Dispose()}
""".replace('\n',e).encode()
            (root/BASE).parent.mkdir(parents=True)
            (root/BASE).write_bytes(base)
            mp=root/DESCMAN;mp.parent.mkdir(parents=True)
            mp.write_text(json.dumps(dict(tag='BB622_DESCENT_SWAP_V1',files=[dict(path=BASE,installed=SHA(base))])))
            b=preview(root)
            assert b'bb622-picprobe.request' in b and b'0x19' in b
            assert b'HOST_CONTROL_V1' in b
            assert b.count(b'Start-Sleep -Milliseconds 15')==1
            apply(root)
            verify(root)
            assert (root/BASE).read_bytes()==base
            restore(root)
            assert (root/BASE).read_bytes()==base
            assert not (root/NEW).exists() and not (root/REQUEST).exists()
    print('SELFTEST PASS LF/CRLF, source SHA, host polling injection, exact rollback')

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('command',choices=['selftest','probe','apply','verify','restore','status'])
    a.add_argument('--root',type=Path,default=ROOT)
    v=a.parse_args()
    try:
        {'selftest':selftest,'probe':lambda:preview(v.root),'apply':lambda:apply(v.root),
         'verify':lambda:verify(v.root),'restore':lambda:restore(v.root),
         'status':lambda:check_firmware(v.root)}[v.command]()
    except Exception as ex:
        print('ERROR:',ex,file=sys.stderr);sys.exit(1)
