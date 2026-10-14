#!/usr/bin/env python3
"""Opt-in DOS 6.22 C: boot + A:/B: eject, with byte-exact rollback.

Requires installed BB_DOS622_SWAP_LCD_V2 and bb_dos622_swap_lcd_v2_2.py
(also bb_dos622_atbios_v1.py). No DOS image or existing runner overwritten.
Commands: selftest, probe, apply, verify, restore.
"""
from __future__ import annotations
import sys,os,re,hashlib,json,shutil,argparse,tempfile
from pathlib import Path
import bb_dos622_swap_lcd_v2_2 as parent
ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_BOOT_EJECT_V1';STATE='.bb_dos622_boot_eject_v1_state'
SD='sd_boot/bb_dos622_sd.inc';SDB='sd_boot/bb_sd_boot.c';BIOS='src/bb_dos622_bios.inc';LIVE='src/bb_live.c'
BASE_RUN='scripts/bb_live_run_dos622_controls.ps1'; NEW_RUN='scripts/bb_live_run_dos622_boot_eject.ps1'
NEW_REQUEST='scripts/bb622_request_media.ps1'
SHA=lambda b:hashlib.sha256(b).hexdigest()

def parse(b):
    bom=b.startswith(b'\xef\xbb\xbf');s=b.decode('utf-8-sig')
    if '\r\n' in s and '\n' in s.replace('\r\n',''):raise ValueError('mixed newline convention')
    return s.replace('\r\n','\n'),'\r\n' if '\r\n' in s else '\n',bom

def pack(s,e,bom):return (b'\xef\xbb\xbf' if bom else b'')+s.replace('\n',e).encode('utf-8')

def one(s,a,b,label):
    count=s.count(a)
    if count!=1:raise ValueError(f'{label}: expected one anchor, found {count}')
    return s.replace(a,b,1)

A_EJECT=r'''/* BB_DOS622_BOOT_EJECT_V1: eject A without ending the DOS6 session.
 * The running OS owns DOS6, but a floppy may temporarily have no media.
 */
bool bb_sd_dos622_a_image_ready(void) { return bb622_disk_open && !bb622_swap_a_ejected; }
bool bb_sd_dos622_eject_a(void)
{
    if(!bb622_disk_open) return false;
    if(!bb622_swap_a_ejected) {
        bb622_retime_spi1();
        (void)f_close(bb622_swap_active);
        bb622_swap_a_ejected=true;
    }
    bb622_swap_a_changed=true;
    printf("[bb622-swap] A:0 OK ejected; BIOS media changed\n");fflush(stdout);
    return true;
}
'''
B_EJECT=r'''/* BB_DOS622_BOOT_EJECT_V1: eject physical B but keep the drive present. */
bool bb_sd_dos622_eject_b(void)
{
    if(!bb_sd_dos622_active())return false;
    if(bb_b_open){
        (void)spi_set_baudrate(spi1,12500000u);
        (void)f_close(&bb_b_img);
        bb_b_open=false;
    }
    bb_b_number=0u;
    bb622_swap_b_changed=true;
    printf("[bb622-swap] B:0 OK ejected; BIOS media changed\n");fflush(stdout);
    return true;
}
'''
BOOT_PICK=r'''/* BB_DOS622_BOOT_EJECT_V1: explicit cold-boot selector on the microSD.
 * The legacy DOS2 path and default DOS6 A: boot are unchanged.
 * C requires BOOT_DRIVE.TXT containing the single ASCII letter C.
 */
extern bool bb_sd_hdd_available(void);
static char bb622_boot_drive='A';
static void bb622_pick_boot(const char *drive)
{
    FIL f;FRESULT rc;UINT got=0;char choice='A';char path[96];
    bb622_boot_drive='A';
    if(!bb_sd_dos622_active())return;
    if(snprintf(path,sizeof path,"%s/BLITZBUS/BOOT_DRIVE.TXT",drive)>=(int)sizeof path)return;
    rc=f_open(&f,path,FA_READ);
    if(rc==FR_OK){
        rc=f_read(&f,&choice,1u,&got);
        (void)f_close(&f);
        if(rc==FR_OK && got==1u && (choice=='C'||choice=='c'))bb622_boot_drive='C';
        else if(choice!='A' && choice!='a')printf("[bb622-boot] invalid BOOT_DRIVE.TXT, using A\n");
    }
    if(bb622_boot_drive=='C' && !bb_sd_hdd_available()) {
        printf("[bb622-boot] C requested but HDD absent; fallback A\n");
        bb622_boot_drive='A';
    }
    printf("[bb622-boot] cold boot selector=%c (A=setup, C=installed HDD)\n",bb622_boot_drive);
}
bool bb_sd_dos622_boot_c(void) {return bb622_boot_drive=='C';}
'''

def sd_patch(b):
    s,e,bom=parse(b)
    if TAG in s:raise ValueError('A source already modified')
    s=one(s,'static bool bb622_swap_a_changed;','static bool bb622_swap_a_changed;\nstatic bool bb622_swap_a_ejected;','A eject variable')
    s=one(s,'if (!bb622_disk_open || !dst || length != 512u || lba >= 2880u) return false;',
          'if (!bb622_disk_open || bb622_swap_a_ejected || !dst || length != 512u || lba >= 2880u) return false;','A read empty guard')
    s=one(s,'    if(!bb622_disk_open || n<1u || n>9u)return false;','    if(!bb622_disk_open || n<1u || n>9u)return false;','A n guard')
    s=one(s,'    if(n==bb622_swap_a_number)return true;','    if(n==bb622_swap_a_number && !bb622_swap_a_ejected)return true;','A reinsert same')
    s=one(s,'    bb622_swap_a_number=n;\n    bb622_swap_a_changed=true;',
          '    bb622_swap_a_number=n;\n    bb622_swap_a_ejected=false;\n    bb622_swap_a_changed=true;','A successful reinsertion')
    s=one(s,'bb622_swap_a_number=1u;bb622_swap_a_changed=false;',
          'bb622_swap_a_number=1u;bb622_swap_a_changed=false;bb622_swap_a_ejected=false;','A init')
    s=one(s,'/* DOS 6.x floppy boot candidates need the ordinary 1.44MB FAT12 layout.',
          A_EJECT+'\n'+BOOT_PICK+'\n/* DOS 6.x floppy boot candidates need the ordinary 1.44MB FAT12 layout.','A funcs + selector')
    return pack(s,e,bom)

def sdboot_patch(b):
    s,e,bom=parse(b)
    if TAG in s:raise ValueError('B source already modified')
    s=one(s,'    bb622_hd_mount(drive); /* BB_DOS622_HDD_V1 */',
          '    bb622_hd_mount(drive); /* BB_DOS622_HDD_V1 */\n    bb622_pick_boot(drive); /* BB_DOS622_BOOT_EJECT_V1 */','cold boot choice')
    s=one(s,'/* BB_DESCENT_LIVESWAP_V1. Called only by the emulator\'s INT F6 service. */',
          B_EJECT+'\n/* BB_DESCENT_LIVESWAP_V1. Called only by the emulator\'s INT F6 service. */','B eject func')
    return pack(s,e,bom)

def bios_patch(b):
    s,e,bom=parse(b)
    if TAG in s:raise ValueError('BIOS already modified')
    s=one(s,'extern bool bb_sd_b_read_sector(uint32_t lba,uint8_t *dst,size_t size);',
          '''extern bool bb_sd_b_read_sector(uint32_t lba,uint8_t *dst,size_t size);
/* BB_DOS622_BOOT_EJECT_V1: physical drive still exists after media eject. */
extern bool bb_sd_dos622_a_image_ready(void);
extern bool bb_sd_dos622_boot_c(void);''','bios extern')
    s=one(s,'    if(!bb_sd_dos622_b_image_ready()) {bb622_status(c,0x80u,0u);return true;}',
          '    if(!bb_sd_dos622_b_image_ready() && fn!=0x00u && fn!=0x08u && fn!=0x15u && fn!=0x16u) {bb622_status(c,0x80u,0u);return true;}','B no-media guard')
    s=one(s,'c->r[MD_X86_DX] = bb_sd_dos622_b_image_ready()?0x0102u:0x0101u;',
          'c->r[MD_X86_DX] = 0x0102u;','bios A enumeration')
    s=one(s,'    if (fn != 0x02u && fn != 0x04u) { bb622_status(c, 0x01u, 0u); return true; }',
          '    if (fn != 0x02u && fn != 0x04u) { bb622_status(c, 0x01u, 0u); return true; }\n    if (drive==0u && !bb_sd_dos622_a_image_ready()) {bb622_status(c,0x80u,0u);return true;}','bios A no-media guard')
    s=one(s,'    case 0x11u: c->r[MD_X86_AX] = bb_sd_dos622_b_image_ready()?0x0061u:0x0021u; return true;',
          '    case 0x11u: c->r[MD_X86_AX] = 0x0061u; return true; /* BB_DOS622_BOOT_EJECT_V1: two physical drives */','bios equipment int11')
    s=one(s,'    md_x86_write16(c, 0x0040u, 0x0010u, bb_sd_dos622_b_image_ready()?0x0061u:0x0021u);',
          '    md_x86_write16(c, 0x0040u, 0x0010u, 0x0061u);','bios equipment BDA')
    # C opt-in boot: physical sector 0 of BIOS 80h is the MBR (not partition LBA 63).
    pre=r'''    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) {
        printf("[bb622-diag] 13 sector0.FAILED\n"); fflush(stdout);
        return false;
    }'''
    if s.count(pre)!=1:raise ValueError('bios boot sector loader: expected exact anchor once')
    repl=r'''    /* BB_DOS622_BOOT_EJECT_V1: opt-in BIOS HDD 80h MBR, else legacy A:. */
    bool boot_c=bb_sd_dos622_boot_c() && bb_sd_hdd_available();
    if(boot_c) {
        if(!bb_sd_hdd_read_sector(0u,bb622_sector,sizeof bb622_sector) ||
           bb622_sector[510]!=0x55u || bb622_sector[511]!=0xAAu ||
           bb622_sector[446]!=0x80u) {
            printf("[bb622-boot] invalid/unreadable C: MBR; falling back A:\n");
            boot_c=false;
        }
    }
    if(!boot_c && !bb_sd_dos622_read_sector(0u,bb622_sector,sizeof bb622_sector)) {
        printf("[bb622-diag] 13 sector0.FAILED\n");fflush(stdout);
        return false;
    }'''
    s=one(s,pre,repl,'C MBR IPL loader')
    s=one(s,'    c->r[MD_X86_DX] &= 0xFF00u; /* DL=00 BIOS A: */',
          '''    c->r[MD_X86_DX] = (uint16_t)((c->r[MD_X86_DX]&0xFF00u) | (boot_c?0x80u:0u)); /* boot DL */''','C boot DL')
    s=one(s,'    printf("[bb-dos622] ENTER real boot sector 0000:7C00, BIOS DL=00; image read-only\\n");',
          '''    printf("[bb622-boot] ENTER %c: at 0000:7C00 BIOS DL=%02X\\n",boot_c?'C':'A',boot_c?0x80u:0u);''','C boot log')
    return pack(s,e,bom)

def live_patch(b):
    s,e,bom=parse(b)
    if TAG in s:raise ValueError('LIVE already modified')
    s=one(s,'extern bool bb_sd_b_select(unsigned n);',
          '''extern bool bb_sd_b_select(unsigned n);
extern bool bb_sd_dos622_eject_a(void);
extern bool bb_sd_dos622_eject_b(void); /* BB_DOS622_BOOT_EJECT_V1 */''','LIVE extern')
    s=one(s,"    if(ch<'1'||ch>'9')return;","    if(ch<'0'||ch>'9')return;",'eject token')
    s=one(s,"        bool success=(bb622_swap_drive=='A') ? bb_sd_dos622_select_a(number) :\n                                              bb_sd_b_select(number);",
          """        bool success=(bb622_swap_drive=='A') ?
                     (number==0u?bb_sd_dos622_eject_a():bb_sd_dos622_select_a(number)) :
                     (number==0u?bb_sd_dos622_eject_b():bb_sd_b_select(number));""",'LIVE ejection dispatcher')
    # Avoid duplicate B ejection log, keep disk status compatible with host ACK parser.
    s=one(s,"        if(bb622_swap_drive=='B') {","        if(bb622_swap_drive=='B' && number!=0u) {",'B logging duplicate')
    return pack(s,e,bom)

def host_patch(b):
    s,e,bom=parse(b)
    if 'BB622_SWAP_CONTROLS_V1' not in s:raise ValueError('expected V1 host runner')
    s=one(s,"$bb622Raw -match '^[AB][1-9]$'","$bb622Raw -match '^[AB][0-9]$'",'host file request eject')
    s=one(s,"$k.KeyChar -ge '1' -and $k.KeyChar -le '9'", "$k.KeyChar -ge '0' -and $k.KeyChar -le '9'",'host F9 disk 0')
    s=one(s,"$number=[string]$k.KeyChar", "$number=[string]$k.KeyChar # BB_DOS622_BOOT_EJECT_V1: disk 0 eject",'host marker')
    return pack(s,e,bom)

MEDIA_POWERSHELL=r'''[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][ValidateSet('A','B')][string]$Drive,
 [Parameter(Mandatory=$true)][ValidateRange(0,9)][int]$Disk,
 [ValidateRange(1,120)][int]$TimeoutSeconds=20
)
$ErrorActionPreference='Stop'
if($Drive -eq 'B' -and $Disk -gt 5){throw 'B disks are 0 (eject) or 1..5'}
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir=Join-Path $root 'logs'
$target=Join-Path $logDir 'bb622-swap.request'
if(Test-Path -LiteralPath $target){throw "Previous request pending: $target"}
$log=Get-ChildItem -LiteralPath $logDir -Filter 'bb-live-*-console.txt' -File |
     Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(!$log){throw 'No live Pico capture log. Start the new DOS622 boot/eject console first.'}
if(([datetime]::UtcNow-$log.LastWriteTimeUtc).TotalSeconds -gt 20){
 Write-Warning "Console log has no recent output; cannot confirm runner is still active until an ACK arrives."
}
$initial=[System.IO.FileInfo]::new($log.FullName).Length
$command=$Drive+[string]$Disk
$temp=$target+'.new.'+[guid]::NewGuid().ToString('N')
try{
 [System.IO.File]::WriteAllText($temp,$command,[System.Text.Encoding]::ASCII)
 [System.IO.File]::Move($temp,$target)
}finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Force}}
Write-Host "Submitted $command; waiting for Pico's [bb622-swap] response..."
$deadline=[datetime]::UtcNow.AddSeconds($TimeoutSeconds)
$escaped=[regex]::Escape($Drive+':'+[string]$Disk)
while([datetime]::UtcNow -lt $deadline){
 Start-Sleep -Milliseconds 200
 try {
  $file=[System.IO.File]::Open($log.FullName,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
  try {
   if($file.Length -gt $initial){
    [void]$file.Seek($initial,[System.IO.SeekOrigin]::Begin)
    $reader=[System.IO.StreamReader]::new($file,[System.Text.Encoding]::UTF8,$true,4096,$true)
    try {$newLog=$reader.ReadToEnd()} finally {$reader.Dispose()}
    if($newLog -match "(?m)^\[bb622-swap\] $escaped OK\b") {
      Write-Host "PICO CONFIRMED OK: $command" -ForegroundColor Green
      exit 0
    }
    if($newLog -match "(?m)^\[bb622-swap\] $escaped FAIL\b") {
      Write-Host "PICO REJECTED: $command (see raw log)" -ForegroundColor Red
      exit 2
    }
   }
  } finally {$file.Dispose()}
 } catch {[void]0} # A writer may briefly lock the log; retry without losing the request.
}
Write-Host "NO FIRMWARE ACK after $TimeoutSeconds seconds. Do not continue DOS Setup." -ForegroundColor Red
if(Test-Path -LiteralPath $target){
 try {
  if([System.IO.File]::ReadAllText($target).Trim() -eq $command){
   Remove-Item -LiteralPath $target -Force
   Write-Host 'Unconsumed request cleaned up to prevent a stale swap later.'
  }
 } catch {Write-Warning "Could not clean request: $_"}
}
Write-Host "Raw log: $($log.FullName)"
exit 3
'''

FUNCTIONS={SD:sd_patch,SDB:sdboot_patch,BIOS:bios_patch,LIVE:live_patch}
NEW={NEW_RUN:None,NEW_REQUEST:MEDIA_POWERSHELL.encode('utf8')}

def prepare(root:Path=ROOT,verbose=True):
    if (root/STATE).exists():raise ValueError('Already installed; use verify/restore')
    p=root/'.bb_dos622_swap_lcd_v2_state'/'manifest.json'
    if not p.is_file():raise ValueError('Missing installed DOS622 swap LCD V2 layer')
    m=json.loads(p.read_bytes())
    if m.get('tag')!='BB_DOS622_SWAP_LCD_V2':raise ValueError('wrong predecessor tag')
    if not (root/BASE_RUN).is_file():raise ValueError('Missing stable V1 controls runner: '+BASE_RUN)
    v1=root/'.bb622_swap_controls_v1_state'/'manifest.json'
    if not v1.is_file():raise ValueError('Missing V1 controls checksum manifest')
    hv=json.loads(v1.read_bytes())
    if SHA((root/BASE_RUN).read_bytes())!=hv.get('outputs',{}).get(BASE_RUN):
        raise ValueError('V1 controls runner changed; refusing to derive eject host')
    for rel in NEW:
        if (root/rel).exists():raise ValueError('Will not overwrite '+rel)
    changes={}
    for rel,fn in FUNCTIONS.items():
        old=(root/rel).read_bytes()
        new=fn(old)
        changes[rel]=(old,new)
    changes[NEW_RUN]=(None,host_patch((root/BASE_RUN).read_bytes()))
    changes[NEW_REQUEST]=(None,MEDIA_POWERSHELL.encode('utf8'))
    meta=parent.cascade(root,{k:v for k,v in changes.items() if v[0] is not None})
    for k,v in meta.items():
        if k in changes:raise ValueError('metadata overlaps new source '+k)
    changes.update(meta)
    if verbose:print(f'PROBE PASS: {len(FUNCTIONS)} firmware sources, 2 NEW host scripts, {len(meta)} metadata files; no files edited')
    return changes

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.bb622-boot-temp')
    try:tmp.write_bytes(data);os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def verify(root:Path=ROOT):
    mp=root/STATE/'manifest.json'
    if not mp.is_file():raise ValueError('No install manifest')
    m=json.loads(mp.read_bytes());assert m['tag']==TAG
    for f in m['files']:
        path=f['path'];p=root/path
        if Path(path).is_absolute() or '..' in Path(path).parts:raise ValueError('unsafe path')
        if not p.is_file() or SHA(p.read_bytes())!=f['installed']:raise ValueError('Installed hash mismatch '+path)
        if f['original'] is not None:
            b=root/STATE/f['backup']
            if not b.is_file() or SHA(b.read_bytes())!=f['original']:raise ValueError('Backup mismatch '+path)
    print('VERIFY PASS:',len(m['files']),'source/host/metadata entries and backups')

def apply(root:Path=ROOT):
    ch=prepare(root)
    state=root/STATE;state.mkdir();rows=[];done=[]
    try:
        for i,(rel,(old,new)) in enumerate(ch.items()):
            backup=None
            if old is not None:
                backup=f'backup_{i:03d}.bin';atomic(state/backup,old)
            rows.append(dict(path=rel,backup=backup,original=SHA(old) if old is not None else None,installed=SHA(new)))
        atomic(state/'manifest.json',(json.dumps(dict(tag=TAG,files=rows),indent=2)+'\n').encode())
        for rel,(old,new) in ch.items():atomic(root/rel,new);done.append(rel)
        verify(root)
    except BaseException:
        for rel in reversed(done):
            old=ch[rel][0]
            if old is None:(root/rel).unlink(missing_ok=True)
            else:atomic(root/rel,old)
        shutil.rmtree(state,ignore_errors=True);raise
    print('APPLIED: C boot opt-in, A/B disk-0 eject, new host runner. Images remain untouched.')

def restore(root:Path=ROOT):
    verify(root)
    m=json.loads((root/STATE/'manifest.json').read_bytes())
    for f in reversed(m['files']):
        path=root/f['path']
        if f['original'] is None:path.unlink()
        else:atomic(path,(root/STATE/f['backup']).read_bytes())
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: byte-exact prior firmware, scripts, metadata')

def selftest():
    # Try source transformations with the source anchors from checked repository.
    src={
       SD:('''static bool bb622_swap_a_changed;\nif (!bb622_disk_open || !dst || length != 512u || lba >= 2880u) return false;\n    if(!bb622_disk_open || n<1u || n>9u)return false;\n    if(n==bb622_swap_a_number)return true;\n    bb622_swap_a_number=n;\n    bb622_swap_a_changed=true;\nbb622_swap_a_number=1u;bb622_swap_a_changed=false;\n/* DOS 6.x floppy boot candidates need the ordinary 1.44MB FAT12 layout. */\n'''),
       SDB:('''    bb622_hd_mount(drive); /* BB_DOS622_HDD_V1 */\n/* BB_DESCENT_LIVESWAP_V1. Called only by the emulator's INT F6 service. */\n'''),
       BIOS:(r'''extern bool bb_sd_b_read_sector(uint32_t lba,uint8_t *dst,size_t size);
    if(!bb_sd_dos622_b_image_ready()) {bb622_status(c,0x80u,0u);return true;}
c->r[MD_X86_DX] = bb_sd_dos622_b_image_ready()?0x0102u:0x0101u;
    if (fn != 0x02u && fn != 0x04u) { bb622_status(c, 0x01u, 0u); return true; }
    case 0x11u: c->r[MD_X86_AX] = bb_sd_dos622_b_image_ready()?0x0061u:0x0021u; return true;
    md_x86_write16(c, 0x0040u, 0x0010u, bb_sd_dos622_b_image_ready()?0x0061u:0x0021u);
    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) {
        printf("[bb622-diag] 13 sector0.FAILED\n"); fflush(stdout);
        return false;
    }
    c->r[MD_X86_DX] &= 0xFF00u; /* DL=00 BIOS A: */
    printf("[bb-dos622] ENTER real boot sector 0000:7C00, BIOS DL=00; image read-only\n");
'''),
       LIVE:('''extern bool bb_sd_b_select(unsigned n);\n    if(ch<'1'||ch>'9')return;\n        bool success=(bb622_swap_drive=='A') ? bb_sd_dos622_select_a(number) :\n                                              bb_sd_b_select(number);\n        if(bb622_swap_drive=='B') {\n''')
    }
    host='''# BB622_SWAP_CONTROLS_V1\n$bb622Raw -match '^[AB][1-9]$'\n$k.KeyChar -ge '1' -and $k.KeyChar -le '9'\n$number=[string]$k.KeyChar\n'''
    for newline in ('\n','\r\n'):
        for rel,fn in FUNCTIONS.items():
            b=src[rel].replace('\n',newline).encode();out=fn(b);s,sep,_=parse(out)
            assert TAG in s and sep==newline
        assert b'disk 0 eject' in host_patch(host.replace('\n',newline).encode())
    # Verify real filesystem transaction and exact restore on isolated fixtures.
    # Cascade is mocked only in this fixture; live probe always uses the real SHA graph.
    original_cascade=parent.cascade
    try:
        parent.cascade=lambda root,changes: {}
        for ending in ('\n','\r\n'):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                original={}
                for rel,value in src.items():
                    q=root/rel;q.parent.mkdir(parents=True,exist_ok=True)
                    payload=value.replace('\n',ending).encode('utf8');q.write_bytes(payload)
                    original[rel]=payload
                q=root/BASE_RUN;q.parent.mkdir(parents=True,exist_ok=True)
                payload=host.replace('\n',ending).encode('utf8');q.write_bytes(payload)
                original[BASE_RUN]=payload
                prior=root/'.bb_dos622_swap_lcd_v2_state';prior.mkdir()
                (prior/'manifest.json').write_text(json.dumps({'tag':'BB_DOS622_SWAP_LCD_V2','files':[]}),encoding='utf8')
                prior=root/'.bb622_swap_controls_v1_state';prior.mkdir()
                (prior/'manifest.json').write_text(json.dumps({'outputs':{BASE_RUN:SHA(payload)}}),encoding='utf8')
                assert len(prepare(root,False))==6
                apply(root);verify(root);restore(root)
                for rel,content in original.items():assert (root/rel).read_bytes()==content
                assert not (root/STATE).exists()
                for rel in NEW:assert not (root/rel).exists()
    finally:
        parent.cascade=original_cascade
    print('SELFTEST PASS: LF/CRLF source transforms, isolated full apply/verify/restore, byte-exact rollback (Pico not compiled)')

def main():
    arg=argparse.ArgumentParser(description=__doc__);arg.add_argument('action',choices=['selftest','probe','apply','verify','restore']);a=arg.parse_args()
    try:
        {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore}[a.action]()
    except (ValueError,OSError,KeyError,AssertionError,ImportError) as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
