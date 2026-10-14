#!/usr/bin/env python3
"""Create independent DOS622 live-swap console with Ctrl+G + out-of-band request.
No modifications to installed firmware sources, previous runners, or SHA metadata.
Commands: selftest, probe, apply, verify, restore.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ORIG='scripts/bb_live_run_dos622_swap.ps1'
NEW='scripts/bb_live_run_dos622_controls.ps1'
REQ='scripts/bb622_request_disk.ps1'
STATE='.bb622_swap_controls_v1_state'
TAG='BB622_SWAP_CONTROLS_V1'
HASH=lambda b:hashlib.sha256(b).hexdigest()

INJECTION=r'''        # BB622_SWAP_CONTROLS_V1 - out-of-band requests for consoles where F9 is reserved.
        # The runner exclusively owns COM5; callers never open the serial port.
        if ([System.IO.File]::Exists($bb622SwapRequest)) {
            try {
                $bb622Raw = [System.IO.File]::ReadAllText($bb622SwapRequest).Trim().ToUpperInvariant()
                [System.IO.File]::Delete($bb622SwapRequest)
                if ($bb622Raw -match '^[AB][1-9]$') {
                    $bb622DiskDrive = $bb622Raw.Substring(0,1)
                    $bb622DiskNum = $bb622Raw.Substring(1,1)
                    if ($bb622DiskDrive -eq 'B' -and [int]$bb622DiskNum -gt 5) {
                        [Console]::Title = 'blitzBUS disk request rejected: B supports disks 1..5'
                    } else {
                        $serial.Write(([string][char]0x1C)+$bb622DiskDrive+$bb622DiskNum)
                        [System.IO.File]::AppendAllText($log,"[bb622-hostswap] SENT $($bb622DiskDrive):$bb622DiskNum awaiting firmware ACK`n")
                        [Console]::Title="blitzBUS swap $($bb622DiskDrive):$bb622DiskNum submitted; wait for OK then press Enter"
                    }
                } else {
                    [Console]::Title='blitzBUS disk request invalid: expected A2 or B3'
                }
            } catch {
                [Console]::Title='blitzBUS disk request failed: '+[string]$_
            }
        }
'''

REQUEST=r'''[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet('A','B')][string]$Drive,
  [Parameter(Mandatory=$true)][ValidateRange(1,9)][int]$Disk
)
$ErrorActionPreference='Stop'
if ($Drive -eq 'B' -and $Disk -gt 5) { throw 'B: accepts disk numbers 1 through 5' }
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$dir=Join-Path $root 'logs'
[System.IO.Directory]::CreateDirectory($dir) | Out-Null
$target=Join-Path $dir 'bb622-swap.request'
if ([System.IO.File]::Exists($target)) { throw "An earlier disk request is still pending: $target" }
$temp=Join-Path $dir 'bb622-swap-request-writing.tmp'
try {
    if ([System.IO.File]::Exists($temp)) { throw "Another request writer may be active: $temp" }
    [System.IO.File]::WriteAllText($temp,($Drive+$Disk),[System.Text.Encoding]::ASCII)
    [System.IO.File]::Move($temp,$target)
} catch {
    if ([System.IO.File]::Exists($temp)) { [System.IO.File]::Delete($temp) }
    throw
}
Write-Host "Requested $($Drive): disk $Disk. Wait for [bb622-swap] $($Drive):$Disk OK in the runner before pressing Enter in DOS."
'''

def parse(raw):
    bom=raw.startswith(b'\xef\xbb\xbf');s=raw.decode('utf-8-sig')
    if '\r\n' in s and '\n' in s.replace('\r\n',''):raise ValueError('Mixed line endings in original runner')
    e='\r\n' if '\r\n' in s else '\n'
    return s.replace('\r\n','\n'),e,bom

def serialize(s,e,bom):return (b'\xef\xbb\xbf' if bom else b'')+s.replace('\n',e).encode('utf-8')

def unique(s,needle,desc):
    n=s.count(needle)
    if n!=1:raise ValueError(f'{desc}: expected exact anchor once, found {n}')

def transform(src):
    s,e,bom=parse(src)
    if 'BB622_SWAP_CONTROLS_V1' in s:raise ValueError('runner is already patched')
    unique(s,'if($k.Key -eq [ConsoleKey]::F9){','F9 handler')
    s=s.replace('if($k.Key -eq [ConsoleKey]::F9){',
         "if($k.Key -eq [ConsoleKey]::F9 -or $k.KeyChar -eq [char]7 -or "
         "($k.Key -eq [ConsoleKey]::G -and "
         "(($k.Modifiers -band [ConsoleModifiers]::Control) -ne 0))){",
         1)
    unique(s,"$logs=Join-Path $root 'logs'",'log directory')
    s=s.replace("$logs=Join-Path $root 'logs'", 
                "$logs=Join-Path $root 'logs'\n$bb622SwapRequest=Join-Path $logs 'bb622-swap.request'",1)
    unique(s,'        Start-Sleep -Milliseconds 15','runner poll')
    s=s.replace('        Start-Sleep -Milliseconds 15',INJECTION+'        Start-Sleep -Milliseconds 15',1)
    if '$bb622SwapStage=0' not in s or 'BB_DOS622_SWAP_LCD_V2' not in s:
        raise ValueError('Swap source handler missing; refusing to modify unrelated runner')
    return serialize(s,e,bom)

def files(root):return {NEW:transform((root/ORIG).read_bytes()),REQ:REQUEST.encode('utf-8')}

def sha_file(path):return HASH(path.read_bytes())

def check(root):
    state=root/STATE
    if state.exists():raise ValueError('already installed; use verify or restore')
    if not (root/ORIG).is_file():raise ValueError('Missing installed live runner: '+ORIG)
    manifest=root/'.bb_dos622_swap_lcd_v2_state'/'manifest.json'
    if not manifest.is_file():raise ValueError('Missing V2 swap installer state')
    m=json.loads(manifest.read_bytes())
    if m.get('tag')!='BB_DOS622_SWAP_LCD_V2':raise ValueError('Unexpected V2 manifest tag')
    row=next((x for x in m['files'] if x['path']==ORIG),None)
    if row is None or row['installed']!=sha_file(root/ORIG):
        raise ValueError('Installed swap runner checksum does not match its manifest')
    for p in [NEW,REQ]:
        if (root/p).exists():raise ValueError('Will not overwrite '+p)
    new=files(root)
    print('PROBE PASS: verified source runner SHA and F9/serial anchors; no files changed')
    print('Generated:',', '.join(new))
    return new

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.bb622-temp')
    try:temp.write_bytes(data);os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)

def verify(root=ROOT):
    f=root/STATE/'manifest.json'
    if not f.is_file():raise ValueError('Missing independent host-controls install state')
    m=json.loads(f.read_bytes())
    if m.get('tag')!=TAG:raise ValueError('Unexpected host-controls state')
    if sha_file(root/ORIG)!=m['source_sha']:raise ValueError('Original swap runner changed since host fix')
    for path,dig in m['outputs'].items():
        if not (root/path).is_file() or sha_file(root/path)!=dig:
            raise ValueError('Host-controls output was modified: '+path)
    print('VERIFY PASS: existing runner unchanged; independent controls scripts intact')

def apply(root=ROOT):
    produced=check(root)
    state=root/STATE
    m={'tag':TAG,'source_sha':sha_file(root/ORIG),'outputs':{k:HASH(v) for k,v in produced.items()}}
    state.mkdir()
    done=[]
    try:
        atomic(state/'manifest.json',(json.dumps(m,indent=2)+'\n').encode('utf-8'))
        for path,data in produced.items():atomic(root/path,data);done.append(path)
        verify(root)
    except Exception:
        for path in reversed(done):(root/path).unlink(missing_ok=True)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: new host runner and external swap helper; NO Pico source, metadata, or SD image changed')

def restore(root=ROOT):
    verify(root)
    manifest=json.loads((root/STATE/'manifest.json').read_bytes())
    for path in manifest['outputs']:(root/path).unlink()
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: generated scripts removed, existing firmware and runner untouched')

def selftest():
    for ending in ('LF','CRLF'):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'scripts').mkdir()
            (root/'.bb_dos622_swap_lcd_v2_state').mkdir()
            source='''$root='C:/blitzBUS'
$logs=Join-Path $root 'logs'
$bb622SwapStage=0
while ($true) {
                    $k=[Console]::ReadKey($true)
                    # BB_DOS622_SWAP_LCD_V2: floppy menu
                    if($k.Key -eq [ConsoleKey]::F9){
                        $bb622SwapStage=1
                        continue
                    }
        Start-Sleep -Milliseconds 15
}
'''
            raw=serialize(source,'\r\n' if ending=='CRLF' else '\n',ending=='CRLF')
            (root/ORIG).write_bytes(raw)
            manifest={'tag':'BB_DOS622_SWAP_LCD_V2','files':[{'path':ORIG,'installed':HASH(raw)}]}
            (root/'.bb_dos622_swap_lcd_v2_state'/'manifest.json').write_bytes(json.dumps(manifest).encode())
            prepared=check(root)
            assert b'BB622_SWAP_CONTROLS_V1' in prepared[NEW]
            assert b'[char]7' in prepared[NEW]
            assert b'bb622-swap.request' in prepared[NEW]
            assert b'0x1C' in prepared[NEW]
            assert b'\r\n' in prepared[NEW] if ending=='CRLF' else b'\r\n' not in prepared[NEW]
            apply(root);verify(root)
            assert (root/ORIG).read_bytes()==raw
            restore(root)
            assert (root/ORIG).read_bytes()==raw
            assert not (root/NEW).exists() and not (root/REQ).exists()
            print('SELFTEST',ending,'PASS original runner preserved, Ctrl+G and out-of-band request, exact rollback')
    # Refuse wrong checksum to prevent layering on corrupted runner.
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);(root/'scripts').mkdir();(root/'.bb_dos622_swap_lcd_v2_state').mkdir()
        (root/ORIG).write_text('$logs=Join-Path $root \'logs\'',encoding='utf-8')
        (root/'.bb_dos622_swap_lcd_v2_state'/'manifest.json').write_text(json.dumps({'tag':'BB_DOS622_SWAP_LCD_V2','files':[{'path':ORIG,'installed':'0'*64}]}))
        try:check(root)
        except ValueError as e:assert 'checksum' in str(e)
        else:raise AssertionError('checksum mismatch should be blocked')
    print('SELFTEST PASS; PowerShell/COM5 live behavior requires Windows test')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['selftest','probe','apply','verify','restore'])
    a=p.parse_args()
    try:
        {'selftest':selftest,'probe':check,'apply':apply,'verify':verify,'restore':restore}[a.command]()
    except (OSError,ValueError,AssertionError,json.JSONDecodeError) as e:
        print('ERROR:',e);sys.exit(1)
