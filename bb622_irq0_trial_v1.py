#!/usr/bin/env python3
"""BLITZBUS IRQ0 ONE-SHOT V1: controlled first guest IRQ0 experiment.

Requirements: installed .bb622_pic_pending_v1_state and installed
.bb622_pic_host_control_v1_state. No disk image access or modification.
Actions: selftest, probe, apply, verify, restore.
"""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,sys,tempfile
from pathlib import Path
import bb622_pic_pending_v1 as prev

ROOT=Path(__file__).resolve().parent
TAG='BB622_IRQ0_TRIAL_V1'
STATE='.bb622_irq0_trial_v1_state'
PICSTATE='.bb622_pic_pending_v1_state/manifest.json'
HOSTSTATE='.bb622_pic_host_control_v1_state/manifest.json'
SOURCE='src/bb_live.c'
BASE='scripts/bb_live_run_dos622_pic_control.ps1'
RUNNER='scripts/bb_live_run_dos622_irqtrial.ps1'
REQUEST='scripts/bb622_irq0_trial.ps1'
SHA=lambda x: hashlib.sha256(x).hexdigest()

DECL='''/* BB622_IRQ0_TRIAL_V1: guarded runtime guest IRQ0 A/B experiment.
 * OFF after boot. Delivers AT MOST ONE IRQ0 after explicit Ctrl+U arm.
 */
static uint8_t bb622_irq0_trial_armed;
static uint64_t bb622_irq0_trial_started_us;
static uint64_t bb622_irq0_trial_last_report_us;
static uint64_t bb622_irq0_trial_if0_initial;
static uint64_t bb622_irq0_trial_masked_initial;
'''
CONTROL='''    /* BB622_IRQ0_TRIAL_V1: Ctrl+U arms ONE IRQ0, never guest keyboard input. */
    if(bb_sd_dos622_active() && c==0x15){
        bb622_irq0_trial_armed=1u;
        bb622_irq0_trial_started_us=bb_now_us();
        bb622_irq0_trial_last_report_us=bb622_irq0_trial_started_us;
        bb622_irq0_trial_if0_initial=bb_irq36.if_blocked;
        bb622_irq0_trial_masked_initial=bb_irq36.masked;
        printf("[bb622-irqtrial] ARMED one-shot guest IRQ0 (max=1 timeout=8s) irr=%02X imr=%02X isr=%02X if=%u\\n",
               (unsigned)bb_irq36.irr,(unsigned)bb_irq36.imr,(unsigned)bb_irq36.isr,
               (unsigned)((md_x86_flags(&R->cpu)&0x0200u)!=0));
        fflush(stdout);
        return;
    }
'''
TICK='''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
        if (bb_sd_dos622_active()) {
            if(bb622_irq0_trial_armed){
                /* Run original PIC dispatcher only at the synchronized MD
                   guest slice boundary; it checks IF, IMR, ISR and IVT. */
                const uint64_t irq_now=bb_now_us();
                const int was_delivered=bb_irq36_dispatch(rt,irq_now);
                if(was_delivered){
                    bb622_irq0_trial_armed=0u;
                    printf("[bb622-irqtrial] DELIVERED one guest IRQ0; AUTO-OFF delivered=%llu irr=%02X imr=%02X isr=%02X cs:ip=%04X:%04X\\n",
                       (unsigned long long)bb_irq36.delivered,
                       (unsigned)bb_irq36.irr,(unsigned)bb_irq36.imr,
                       (unsigned)bb_irq36.isr,
                       (unsigned)rt->cpu.cs,(unsigned)rt->cpu.ip);
                    fflush(stdout);
                }else if(irq_now-bb622_irq0_trial_started_us>=8000000ull){
                    bb622_irq0_trial_armed=0u;
                    printf("[bb622-irqtrial] TIMEOUT no guest IRQ0 delivered; AUTO-OFF irr=%02X imr=%02X isr=%02X if0_delta=%llu masked_delta=%llu flags=%04X cs:ip=%04X:%04X\\n",
                       (unsigned)bb_irq36.irr,(unsigned)bb_irq36.imr,
                       (unsigned)bb_irq36.isr,
                       (unsigned long long)(bb_irq36.if_blocked-bb622_irq0_trial_if0_initial),
                       (unsigned long long)(bb_irq36.masked-bb622_irq0_trial_masked_initial),
                       (unsigned)md_x86_flags(&rt->cpu),
                       (unsigned)rt->cpu.cs,(unsigned)rt->cpu.ip);
                    fflush(stdout);
                }else if(irq_now-bb622_irq0_trial_last_report_us>=2000000ull){
                    bb622_irq0_trial_last_report_us=irq_now;
                    printf("[bb622-irqtrial] WAIT pending=%02X mask=%02X isr=%02X if0_delta=%llu masked_delta=%llu flags=%04X ip=%04X:%04X\\n",
                        (unsigned)bb_irq36.irr,(unsigned)bb_irq36.imr,
                        (unsigned)bb_irq36.isr,
                        (unsigned long long)(bb_irq36.if_blocked-bb622_irq0_trial_if0_initial),
                        (unsigned long long)(bb_irq36.masked-bb622_irq0_trial_masked_initial),
                        (unsigned)md_x86_flags(&rt->cpu),
                        (unsigned)rt->cpu.cs,(unsigned)rt->cpu.ip);
                    fflush(stdout);
                }
            }else if(bb622_pic_pending_probe_enabled){bb_irq36_schedule(bb_now_us());}
        } else bb_irq36_dispatch(rt, bb_now_us());
#else'''

HOST_POLL=r'''        # BB622_IRQ0_TRIAL_V1: one-shot request from second window.
        if ([System.IO.File]::Exists($bb622IrqTrialRequest)) {
            try {
                $bb622IrqText=[System.IO.File]::ReadAllText($bb622IrqTrialRequest).Trim()
                [System.IO.File]::Delete($bb622IrqTrialRequest)
                if ($bb622IrqText -ceq 'ARM') {
                    $serial.Write([string][char]0x15)
                    [System.IO.File]::AppendAllText($log,"[bb622-irqtrial-host] SENT Ctrl+U 0x15`n")
                } else {
                    [System.IO.File]::AppendAllText($log,"[bb622-irqtrial-host] REJECT request`n")
                }
            } catch {
                [System.IO.File]::AppendAllText($log,"[bb622-irqtrial-host] ERROR $($_.Exception.Message)`n")
            }
        }
'''

REQUESTER=r'''[CmdletBinding()]
param([ValidateRange(2,45)][int]$TimeoutSeconds=15)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dir=Join-Path $root 'logs'
$req=Join-Path $dir 'bb622-irqtrial.request'
$log=Get-ChildItem -LiteralPath $dir -Filter 'bb-live-*-console.txt' -File |
 Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(!$log){throw 'No live raw console log found'}
$age=([datetime]::UtcNow-$log.LastWriteTimeUtc).TotalSeconds
if($age -gt 14){throw "Latest log is stale ($([int]$age)s); start the irqtrial console before requesting"}
if([System.IO.File]::Exists($req)){throw 'Another IRQ0 trial request is pending'}
$start=[System.IO.FileInfo]::new($log.FullName).Length
$tmp=$req+'.new.'+[guid]::NewGuid().ToString('N')
try {
 [System.IO.File]::WriteAllText($tmp,'ARM',[System.Text.Encoding]::ASCII)
 [System.IO.File]::Move($tmp,$req)
} finally {if([System.IO.File]::Exists($tmp)){[System.IO.File]::Delete($tmp)}}
Write-Host 'Requested one-shot guest IRQ0 (one delivery maximum). Waiting for Pico ARM ACK...'
$deadline=[datetime]::UtcNow.AddSeconds($TimeoutSeconds)
$hostSent=$false
while([datetime]::UtcNow -lt $deadline){
 Start-Sleep -Milliseconds 100
 try {
  $f=[System.IO.File]::Open($log.FullName,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
  try {
   if($f.Length -gt $start){
    [void]$f.Seek($start,[System.IO.SeekOrigin]::Begin)
    $sr=[System.IO.StreamReader]::new($f,[System.Text.Encoding]::UTF8,$true,4096,$true)
    try {$new=$sr.ReadToEnd()} finally {$sr.Dispose()}
    if($new.Contains('[bb622-irqtrial-host] SENT Ctrl+U')){$hostSent=$true}
    if($hostSent -and $new -match '(?m)^\[bb622-irqtrial\] ARMED[^\r\n]*'){
     Write-Host "PICO ACK: $($Matches[0])" -ForegroundColor Green
     Write-Host "Log: $($log.FullName)"
     exit 0
    }
    if($new -match '\[bb622-irqtrial-host\] (ERROR|REJECT)'){
     throw 'Host rejected IRQ0 request; check raw log'
    }
   }
  } finally {$f.Dispose()}
 } catch {if($_.Exception.Message -like 'Host rejected*'){throw}}
}
if([System.IO.File]::Exists($req)){
 try {if([System.IO.File]::ReadAllText($req).Trim() -eq 'ARM') {[System.IO.File]::Delete($req)}}catch{}
}
if($hostSent){throw 'HOST SENT but no Pico ARM ACK; check firmware flashed/serial path'}
throw 'HOST DID NOT SEND; run bb_live_run_dos622_irqtrial.ps1'
'''


def src_patch(raw:bytes)->bytes:
    s,e,b=prev.prior.prev.parse(raw)
    if TAG in s:raise ValueError('Source already patched')
    if 'BB622_PIC_PENDING_V1' not in s:raise ValueError('PIC pending probe predecessor missing')
    anchor='''static uint64_t bb622_swap_started_us;'''
    s=prev.prior.prev.one(s,anchor,anchor+'\n'+DECL.rstrip('\n'),'IRQ0 new state')
    picctrl='''    /* BB622_PIC_PENDING_V1: Ctrl+Y is private host control, not guest key.'''
    if s.count(picctrl)!=1:raise ValueError('Ctrl+Y control anchor missing')
    s=s.replace(picctrl,CONTROL+picctrl,1)
    old='''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
        if (bb_sd_dos622_active()) {
            /* BB622_PIC_PENDING_V1: produce 8259 IRR edges at PIT ch0 rate
             * only when explicitly enabled with Ctrl+Y. No stack injection.
             */
            if(bb622_pic_pending_probe_enabled)bb_irq36_schedule(bb_now_us());
        } else bb_irq36_dispatch(rt, bb_now_us());
#else'''
    s=prev.prior.prev.one(s,old,TICK,'IRQ0 pending-only scheduling gate')
    s=prev.prior.prev.one(s,'    bb622_pic_pending_probe_enabled=0u; /* BB622_PIC_PENDING_V1: OFF on cold boot */',
            '    bb622_pic_pending_probe_enabled=0u; /* BB622_PIC_PENDING_V1: OFF on cold boot */\n    bb622_irq0_trial_armed=0u; /* BB622_IRQ0_TRIAL_V1: OFF on cold boot */',
            'cold boot reset')
    return prev.prior.prev.pack(s,e,b)

def host_patch(raw:bytes)->bytes:
    s,e,b=prev.prior.prev.parse(raw)
    if TAG in s:raise ValueError('Host already patched')
    anchor="$bbPicToggleRequest=Join-Path $logs 'bb622-picprobe.request'"
    s=prev.prior.prev.one(s,anchor,
            anchor+"\n$bb622IrqTrialRequest=Join-Path $logs 'bb622-irqtrial.request'",'request path')
    sleep='        Start-Sleep -Milliseconds 15'
    s=prev.prior.prev.one(s,sleep,HOST_POLL+sleep,'IRQ0 requester polling')
    return prev.prior.prev.pack(s,e,b)

def atomic(p:Path,b:bytes):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.bb622_irq0_new')
    try:tmp.write_bytes(b);os.replace(tmp,p)
    finally:tmp.unlink(missing_ok=True)

def update_previous_pic_manifest(raw:bytes,changes:dict[str,tuple[bytes|None,bytes]])->bytes:
    obj=json.loads(raw)
    if obj.get('tag')!='BB622_PIC_PENDING_V1' or not isinstance(obj.get('files'),list):
        raise ValueError('PIC manifest schema mismatch')
    touched=0
    for row in obj['files']:
        rel=row['path']
        if rel in changes:
            old,new=changes[rel]
            if old is None or row['installed']!=SHA(old):raise ValueError('PIC checksum precondition mismatch: '+rel)
            row['installed']=SHA(new);touched+=1
    if not touched:raise ValueError('No relevant PIC tracked SHA transitions')
    new=(json.dumps(obj,indent=2)+'\n').encode('utf-8')
    return new.replace(b'\n',b'\r\n') if b'\r\n' in raw else new

def prepare(root:Path=ROOT,quiet=False,fixture=False):
    if (root/STATE).exists():raise ValueError('Already installed; run verify/restore')
    for rel in [SOURCE,BASE,PICSTATE,HOSTSTATE]:
        if not (root/rel).is_file():raise ValueError('Missing prerequisite: '+rel)
    picstate=json.loads((root/PICSTATE).read_bytes())
    hstate=json.loads((root/HOSTSTATE).read_bytes())
    if picstate.get('tag')!='BB622_PIC_PENDING_V1':raise ValueError('PIC predecessor tag mismatch')
    if hstate.get('tag')!='BB622_PIC_HOST_CONTROL_V1' or hstate.get('outputs',{}).get(BASE)!=SHA((root/BASE).read_bytes()):
        raise ValueError('Host predecessor checksum mismatch (required pic-control runner)')
    for rel in [RUNNER,REQUEST]:
        if (root/rel).exists():raise ValueError('Refusing to overwrite '+rel)
    old=(root/SOURCE).read_bytes()
    changes={SOURCE:(old,src_patch(old)),RUNNER:(None,host_patch((root/BASE).read_bytes())),REQUEST:(None,REQUESTER.encode('utf8'))}
    if not fixture:
        parent=prev.prior.prev.parent.cascade(root,{SOURCE:changes[SOURCE]})
        if set(parent)&set(changes):raise ValueError('Metadata/source overlap')
        changes.update(parent)
    old_manifest=(root/PICSTATE).read_bytes()
    new_manifest=update_previous_pic_manifest(old_manifest,changes)
    if new_manifest!=old_manifest:changes[PICSTATE]=(old_manifest,new_manifest)
    if not quiet:print('PROBE PASS: guarded firmware IRQ0 path, 2 new host scripts, '+str(len(changes)-3)+' metadata files; HDD untouched')
    return changes

def verify(root:Path=ROOT):
    mp=root/STATE/'manifest.json'
    if not mp.is_file():raise ValueError('No one-shot experiment install manifest')
    obj=json.loads(mp.read_bytes())
    if obj.get('tag')!=TAG:raise ValueError('Unexpected one-shot experiment tag')
    for row in obj['files']:
        rel=row['path'];p=root/rel
        if not p.is_file() or SHA(p.read_bytes())!=row['installed']:raise ValueError('Current SHA mismatch: '+rel)
        if row['original'] is not None:
            backup=root/STATE/row['backup']
            if SHA(backup.read_bytes())!=row['original']:raise ValueError('Backup SHA mismatch: '+rel)
    print(f'VERIFY PASS: {len(obj["files"])} sources/hosts/metadata; backups byte-exact')

def apply(root:Path=ROOT,fixture=False):
    changes=prepare(root,fixture=fixture)
    state=root/STATE
    state.mkdir();done=[]
    try:
        rows=[]
        for i,(rel,(old,new)) in enumerate(changes.items()):
            backup=f'backup_{i:03d}.bin' if old is not None else None
            if backup:atomic(state/backup,old)
            rows.append({'path':rel,'backup':backup,'original':SHA(old) if old is not None else None,'installed':SHA(new)})
        atomic(state/'manifest.json',(json.dumps({'tag':TAG,'files':rows},indent=2)+'\n').encode())
        for rel,(old,new) in changes.items():atomic(root/rel,new);done.append(rel)
        verify(root)
    except BaseException:
        for rel in reversed(done):
            old=changes[rel][0]
            if old is None:(root/rel).unlink(missing_ok=True)
            else:atomic(root/rel,old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: guarded 1-IRQ experimental path; OFF at cold boot; SD/HDD unchanged')

def restore(root:Path=ROOT):
    verify(root)
    rows=json.loads((root/STATE/'manifest.json').read_bytes())['files']
    for row in reversed(rows):
        rel=row['path'];old=(root/STATE/row['backup']).read_bytes() if row['original'] else None
        if old is None:(root/rel).unlink()
        else:atomic(root/rel,old)
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: source and prior metadata restored byte-exactly')

def selftest():
    live='''/* BB_DOS622_BOOT_EJECT_V1 */
static uint64_t bb622_swap_started_us;
    /* BB622_PIC_PENDING_V1: Ctrl+Y is private host control, not guest key.
     * This intentionally does not call bb_irq36_dispatch() or push FLAGS/CS/IP.
     */
    bb_irq36_init(bb_now_us());
    bb622_pic_pending_probe_enabled=0u; /* BB622_PIC_PENDING_V1: OFF on cold boot */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
        if (bb_sd_dos622_active()) {
            /* BB622_PIC_PENDING_V1: produce 8259 IRR edges at PIT ch0 rate
             * only when explicitly enabled with Ctrl+Y. No stack injection.
             */
            if(bb622_pic_pending_probe_enabled)bb_irq36_schedule(bb_now_us());
        } else bb_irq36_dispatch(rt, bb_now_us());
#else
'''
    base='''# BB622_DESCENT_SWAP_V1
$logs=Join-Path $root 'logs'
$bbPicToggleRequest=Join-Path $logs 'bb622-picprobe.request'
        Start-Sleep -Milliseconds 15
'''
    for e in ('\n','\r\n'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for rel,content in [(SOURCE,live),(BASE,base)]:
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content.replace('\n',e).encode())
            oldsrc=(root/SOURCE).read_bytes();oldbase=(root/BASE).read_bytes()
            prepic=root/PICSTATE;prepic.parent.mkdir(parents=True)
            prepic.write_text(json.dumps({'tag':'BB622_PIC_PENDING_V1','files':[{'path':SOURCE,'original':SHA(oldsrc),'installed':SHA(oldsrc),'backup':'x'}]},indent=2))
            hp=root/HOSTSTATE;hp.parent.mkdir(parents=True)
            hp.write_text(json.dumps({'tag':'BB622_PIC_HOST_CONTROL_V1','outputs':{BASE:SHA(oldbase)}}))
            out=prepare(root,quiet=True,fixture=True)
            assert b'bb622_irq0_trial_armed=1u' in out[SOURCE][1]
            assert out[RUNNER][1].count(b'bb622-irqtrial.request')==1
            assert b'0x15' in out[RUNNER][1]
            assert b'one-shot guest IRQ0' in out[REQUEST][1]
            apply(root,fixture=True);verify(root);restore(root)
            assert (root/SOURCE).read_bytes()==oldsrc and (root/BASE).read_bytes()==oldbase
            assert not (root/STATE).exists() and not (root/RUNNER).exists() and not (root/REQUEST).exists()
    print('SELFTEST PASS LF/CRLF, one IRQ cap, auto-timeout, requester, SHA and rollback')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    ap.add_argument('--root',type=Path,default=ROOT)
    args=ap.parse_args()
    try:
        {'selftest':selftest,'probe':lambda:prepare(args.root),
         'apply':lambda:apply(args.root),
         'verify':lambda:verify(args.root),
         'restore':lambda:restore(args.root)}[args.action]()
    except Exception as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
