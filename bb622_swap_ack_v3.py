#!/usr/bin/env python3
"""DOS622 host-only confirmed swap protocol (works atop BB622_SWAP_CONTROLS_V1).
Commands: selftest, probe, apply, verify, restore. Never alters firmware or disk images.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SOURCE='scripts/bb_live_run_dos622_controls.ps1'
RUN='scripts/bb_live_run_dos622_controls_v3.ps1'
REQ='scripts/bb622_request_disk_v3.ps1'
STATE='.bb622_swap_ack_v3_state'
TAG='BB622_SWAP_ACK_V3'
H=lambda b:hashlib.sha256(b).hexdigest()

def split(data):
    bom=data.startswith(b'\xef\xbb\xbf')
    s=data.decode('utf-8-sig')
    if '\r\n' in s and '\n' in s.replace('\r\n',''):raise ValueError('mixed newline types')
    e='\r\n' if '\r\n' in s else '\n'
    return s.replace('\r\n','\n'),e,bom

def join(s,e,bom):return (b'\xef\xbb\xbf' if bom else b'')+s.replace('\n',e).encode('utf-8')

def unique(s,needle,label):
    n=s.count(needle)
    if n!=1:raise ValueError(f'{label}: exact anchor matches={n}; refusing unsafe change')

def script_source():return Path(__file__).with_name('bb622_request_disk_v3.ps1').read_bytes()

INIT=r'''# BB622_SWAP_ACK_V3: independent, acknowledged swap control plane.
# This host alone owns COM5; external helpers send requests via an atomic file.
$bb622StatusPath=Join-Path $logs 'bb622-swap.status.json'
$bb622SessionPath=Join-Path $logs 'bb622-swap.session.json'
$bb622SessionId=[Guid]::NewGuid().ToString('N')
$bb622SessionAt=[datetime]::UtcNow
$bb622LastHeartbeat=[datetime]::MinValue
$bb622CurrentId=''
$bb622CurrentDisk=''
$bb622CurrentState='IDLE'
$bb622CurrentSent=[datetime]::MinValue
$bb622RxLines=''
function Write-Bb622Json([string]$file,[object]$body) {
    $data=ConvertTo-Json -InputObject $body -Compress -Depth 4
    $temp=$file+'.tmp.'+[Guid]::NewGuid().ToString('N')
    try {
        [System.IO.File]::WriteAllText($temp,$data,[System.Text.Encoding]::UTF8)
        if ([System.IO.File]::Exists($file)) { [System.IO.File]::Delete($file) }
        [System.IO.File]::Move($temp,$file)
    } finally { if ([System.IO.File]::Exists($temp)) { [System.IO.File]::Delete($temp) } }
}
function Set-Bb622SwapState([string]$state,[string]$detail) {
    $script:bb622CurrentState=$state
    $obj=[ordered]@{session=$bb622SessionId;request=$bb622CurrentId;disk=$bb622CurrentDisk;state=$state;detail=$detail;updatedUtc=[datetime]::UtcNow.ToString('o');transcript=$log}
    Write-Bb622Json $bb622StatusPath $obj
    [System.IO.File]::AppendAllText($log,"[bb622-ackhost] $state disk=$bb622CurrentDisk req=$bb622CurrentId $detail`n")
    try { [Console]::Title="blitzBUS $($bb622CurrentDisk): $state | $detail" } catch {}
}
# An earlier console's unconsumed request must not silently reach a new run.
if ([System.IO.File]::Exists($bb622SwapRequest)) {
    [System.IO.File]::Delete($bb622SwapRequest)
    [System.IO.File]::AppendAllText($log,"[bb622-ackhost] STALE REQUEST DISCARDED on new session`n")
}
'''
HEARTBEAT=r'''        # BB622_SWAP_ACK_V3 heartbeat: external caller refuses stale/unstarted consoles.
        $bb622Now=[datetime]::UtcNow
        if (($bb622Now-$bb622LastHeartbeat).TotalMilliseconds -ge 700) {
            Write-Bb622Json $bb622SessionPath ([ordered]@{session=$bb622SessionId;pid=$PID;lastUtc=$bb622Now.ToString('o');startedUtc=$bb622SessionAt.ToString('o');transcript=$log;port=$Port})
            $bb622LastHeartbeat=$bb622Now
        }
        if ($bb622CurrentState -eq 'SENT' -and ($bb622Now-$bb622CurrentSent).TotalSeconds -gt 12) {
            Set-Bb622SwapState 'NO_ACK' 'Pico did not confirm swap within 12 seconds; do NOT press Enter'
        }
'''
ACK=r'''            # BB622_SWAP_ACK_V3: parse complete raw CDC lines, including split reads.
            $bb622RxLines += $chunk
            if ($bb622RxLines.Length -gt 12000) { $bb622RxLines=$bb622RxLines.Substring($bb622RxLines.Length-12000) }
            while ($true) {
                $bb622Nl=$bb622RxLines.IndexOf("`n")
                if ($bb622Nl -lt 0) { break }
                $bb622Line=$bb622RxLines.Substring(0,$bb622Nl).TrimEnd("`r")
                $bb622RxLines=$bb622RxLines.Substring($bb622Nl+1)
                $m=[regex]::Match($bb622Line,'^\[bb622-swap\] ([AB]):([1-9]) (OK|FAIL)\b')
                if ($m.Success -and $bb622CurrentId -and $bb622CurrentDisk -eq ($m.Groups[1].Value+$m.Groups[2].Value)) {
                    if ($bb622CurrentState -eq 'SENT' -or $bb622CurrentState -eq 'NO_ACK') {
                        $result=if ($m.Groups[3].Value -eq 'OK') { 'OK' } else { 'FAIL' }
                        Set-Bb622SwapState $result $bb622Line
                    }
                }
            }
'''
POLL=r'''        # BB622_SWAP_ACK_V3 - validate + transmit an external request.
        if ([System.IO.File]::Exists($bb622SwapRequest)) {
            try {
                $raw=[System.IO.File]::ReadAllText($bb622SwapRequest).Trim().ToUpperInvariant()
                [System.IO.File]::Delete($bb622SwapRequest)
                $match=[regex]::Match($raw,'^([AB])([1-9])\|([A-F0-9]{32})$')
                if (!$match.Success) {
                    $bb622CurrentId='invalid';$bb622CurrentDisk=''
                    Set-Bb622SwapState 'REJECTED' 'Invalid request; expected A2|32-character request ID'
                } elseif ($bb622CurrentState -eq 'SENT') {
                    # Caller must not create a second request until current one resolves.
                    [System.IO.File]::AppendAllText($log,"[bb622-ackhost] BUSY rejected request $raw`n")
                } else {
                    $disk=$match.Groups[1].Value+$match.Groups[2].Value
                    $requestId=$match.Groups[3].Value
                    $bb622CurrentId=$requestId
                    $bb622CurrentDisk=$disk
                    if ($disk[0] -eq 'B' -and [int][string]$disk[1] -gt 5) {
                        Set-Bb622SwapState 'REJECTED' 'B: supports disks 1..5'
                    } else {
                        $bb622CurrentSent=[datetime]::UtcNow
                        $serial.Write(([string][char]0x1C)+[string]$disk[0]+[string]$disk[1])
                        Set-Bb622SwapState 'SENT' 'CDC bytes transmitted; awaiting firmware response'
                    }
                }
            } catch {
                [System.IO.File]::AppendAllText($log,"[bb622-ackhost] REQUEST ERROR $($_)`n")
                try { Set-Bb622SwapState 'HOST_ERROR' ([string]$_) } catch {}
            }
        }
'''

def transform(data):
    s,e,bom=split(data)
    if 'BB622_SWAP_ACK_V3' in s:raise ValueError('already modified by ACK V3')
    if 'BB622_SWAP_CONTROLS_V1' not in s:raise ValueError('source runner missing V1 controls')
    unique(s,'$bb622SwapRequest=Join-Path $logs \'bb622-swap.request\'','swap request path')
    anchor='$log=Join-Path $logs "bb-live-$stamp-console.txt"'
    unique(s,anchor,"raw log path")
    s=s.replace(anchor,anchor+"\n"+INIT,1)
    old_start=s.index('        # BB622_SWAP_CONTROLS_V1 - out-of-band requests')
    old_end=s.index('        Start-Sleep -Milliseconds 15',old_start)
    if '$bb622SwapRequest' not in s[old_start:old_end] or '$serial.Write' not in s[old_start:old_end]:
        raise ValueError('existing request block structure was modified')
    s=s[:old_start]+POLL+s[old_end:]
    unique(s,'        Start-Sleep -Milliseconds 15','runner poll')
    s=s.replace('        Start-Sleep -Milliseconds 15',HEARTBEAT+'        Start-Sleep -Milliseconds 15',1)
    a='            [System.IO.File]::AppendAllText($log,$chunk)'
    unique(s,a,'raw log append')
    s=s.replace(a,a+'\n'+ACK,1)
    # Keep existing F9/Ctrl+G direct-serial control intact; its telemetry
    # remains visible in the raw log. Confirmed second-window requests use IDs.
    # The V1 marker lives in the out-of-band request block replaced above.
    # Checking for it *after* replacement incorrectly rejects valid runners.
    if '$bb622SwapRequest' not in s or 'Set-Bb622SwapState' not in s:
        raise ValueError('ACK V3 control integration incomplete')
    return join(s,e,bom)

def source_verified(root):
    mroot=root/'.bb622_swap_controls_v1_state'/'manifest.json'
    if not mroot.is_file():raise ValueError('Missing installed host-controls V1 state; use existing runner')
    m=json.loads(mroot.read_bytes())
    if m.get('tag')!='BB622_SWAP_CONTROLS_V1':raise ValueError('Invalid V1 controls manifest')
    p=root/SOURCE
    if not p.is_file() or H(p.read_bytes())!=m.get('outputs',{}).get(SOURCE):
        raise ValueError('Existing V1 controls source checksum mismatch; no changes made')
    return p.read_bytes()

def preview(root):
    if (root/STATE).exists():raise ValueError('Already installed; verify or restore')
    raw=source_verified(root)
    if (root/RUN).exists() or (root/REQ).exists():raise ValueError('Refusing to overwrite an existing V3 file')
    outputs={RUN:transform(raw),REQ:script_source()}
    print('PROBE PASS: current V1 runner SHA verified; no source/SD/manifest changes')
    print('Will generate:', ', '.join(outputs))
    return outputs

def verify(root=ROOT):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError('Missing V3 host ACK install manifest')
    obj=json.loads(p.read_bytes())
    if obj.get('tag')!=TAG:raise ValueError('Unexpected V3 host ACK manifest tag')
    if H(source_verified(root))!=obj['sourceSha']:raise ValueError('Source runner changed')
    for f,h in obj['outputs'].items():
        q=root/f
        if not q.is_file() or H(q.read_bytes())!=h:raise ValueError('Generated runner checksum changed: '+f)
    print('VERIFY PASS: host ACK runner+requester checksums, V1 source intact')

def apply(root=ROOT):
    out=preview(root)
    state=root/STATE
    obj={'tag':TAG,'sourceSha':H(source_verified(root)),'outputs':{p:H(v) for p,v in out.items()}}
    state.mkdir()
    try:
        (state/'manifest.json').write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
        for f,data in out.items():
            p=root/f;p.parent.mkdir(parents=True,exist_ok=True)
            with p.open('xb') as fp:fp.write(data)
        verify(root)
    except Exception:
        for f in out:(root/f).unlink(missing_ok=True)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: independent confirmed-swap host scripts only; firmware/images untouched')

def restore(root=ROOT):
    verify(root)
    obj=json.loads((root/STATE/'manifest.json').read_bytes())
    for f in obj['outputs']:(root/f).unlink()
    shutil.rmtree(root/STATE)
    print('RESTORED V3 host scripts; firmware, images and V1 untouched')

def selftest():
    # Simulates the old runner at both newline conventions.
    old='''$root='C:/blitzBUS'
$logs=Join-Path $root 'logs'
$bb622SwapRequest=Join-Path $logs 'bb622-swap.request'
$log=Join-Path $logs "bb-live-$stamp-console.txt"
$bb622SwapStage=0
$bb622SwapDrive=''
while($true) {
  if($chunk){
            [System.IO.File]::AppendAllText($log,$chunk)
  }
        # BB622_SWAP_CONTROLS_V1 - out-of-band requests for consoles where F9 is reserved.
        # The runner exclusively owns COM5; callers never open the serial port.
        if ([System.IO.File]::Exists($bb622SwapRequest)) {
            try {
                $bb622Raw = [System.IO.File]::ReadAllText($bb622SwapRequest).Trim().ToUpperInvariant()
                [System.IO.File]::Delete($bb622SwapRequest)
                if ($bb622Raw -match '^[AB][1-9]$') {
                    $serial.Write(([string][char]0x1C)+$bb622DiskDrive+$bb622DiskNum)
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 15
}
'''
    for newline in ('\n','\r\n'):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            (root/'scripts').mkdir()
            (root/'.bb622_swap_controls_v1_state').mkdir()
            source=join(old,newline,newline=='\r\n')
            (root/SOURCE).write_bytes(source)
            (root/'.bb622_swap_controls_v1_state'/'manifest.json').write_text(json.dumps({'tag':'BB622_SWAP_CONTROLS_V1','outputs':{SOURCE:H(source)}}))
            data=preview(root)[RUN].decode('utf-8-sig')
            for clause in ['BB622_SWAP_ACK_V3','bb622-swap.session.json','NO_ACK','Set-Bb622SwapState','FIRMWARE','[bb622-swap\\]']:
                if clause=='FIRMWARE':continue
                assert clause in data,clause
            assert data.count('Start-Sleep -Milliseconds 15')==1
            assert ('\r\n' in data)==(newline=='\r\n')
            apply(root);verify(root)
            restore(root)
            assert (root/SOURCE).read_bytes()==source
            assert not (root/RUN).exists()
            print('SELFTEST PASS', 'CRLF' if newline=='\r\n' else 'LF','SHA, ACK parser, exact rollback')
    print('SELFTEST PASS; PowerShell/Pico integration not available in Linux container')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['selftest','probe','apply','verify','restore']);args=p.parse_args()
    try:{'selftest':selftest,'probe':lambda:preview(ROOT),'apply':apply,'verify':verify,'restore':restore}[args.command]()
    except (ValueError,OSError,AssertionError,KeyError) as e:
        print('ERROR:',str(e));raise SystemExit(1)
