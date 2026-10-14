#!/usr/bin/env python3
"""BLITZBUS DESCENT SWAP V1: transactional B media + Alt+G console.

Precondition: BB_DOS622_BOOT_EJECT_V1 installed. All files checksum-audited,
backups byte exact; no SD image or DOS2 paths altered. No Git patches.
Commands: selftest, probe, apply, verify, restore.
"""
from __future__ import annotations
import sys, os, re, json, hashlib, shutil, argparse, tempfile, subprocess
from pathlib import Path
import bb622_boot_eject_v1 as prev

ROOT=Path(__file__).resolve().parent
TAG='BB622_DESCENT_SWAP_V1'; STATE='.bb622_descent_swap_v1_state'
SDB='sd_boot/bb_sd_boot.c'; BIOS='src/bb_dos622_bios.inc'
BASE='scripts/bb_live_run_dos622_boot_eject.ps1'
RUN='scripts/bb_live_run_dos622_descent.ps1'
HELPER='scripts/bb622_descent_color_host.ps1'
OLD_HELPER='scripts/bb_dos622_swap_color_host.ps1'
SHA=lambda b:hashlib.sha256(b).hexdigest()

NEW_B_SELECT=r'''/* BB622_DESCENT_SWAP_V1: transactional read-only B: media exchange.
 * Keep the previous image valid until a replacement is opened and checked.
 * The two FIL slots alternate to avoid FatFs replacing an open object.
 * No guest files or the mounted HDD image are modified here.
 */
bool bb_sd_b_select(unsigned selected)
{
    FIL *candidate;
    FRESULT fr;
    UINT got=0u;
    uint8_t boot[512];
    char path[96];
    if(selected<1u || selected>5u || !bb_img_open)return false;
    if(selected==bb_b_number && bb_b_open)return true;
    if(snprintf(path,sizeof path,"0:/BLITZBUS/DESCENT%u.IMG",selected)>=(int)sizeof path)return false;
    (void)spi_set_baudrate(spi1,12500000u);
    candidate=(bb_b_current==&bb_b_img)?&bb_b_swap_alt:&bb_b_img;
    fr=f_open(candidate,path,FA_READ);
    if(fr!=FR_OK){
        printf("[bb-sd-b] LIVE SWITCH B: disk=%u FAIL open fr=%d (previous retained)\n",selected,(int)fr);
        fflush(stdout);
        return false;
    }
    if(f_size(candidate)!=1474560u ||
       f_read(candidate,boot,512u,&got)!=FR_OK || got!=512u ||
       boot[510]!=0x55u || boot[511]!=0xAAu ||
       (boot[0]!=0xEBu && boot[0]!=0xE9u) ||
       boot[11]!=0u || boot[12]!=2u || boot[13]!=1u ||
       boot[16]!=2u || boot[19]!=0x40u || boot[20]!=0x0Bu){
        (void)f_close(candidate);
        printf("[bb-sd-b] LIVE SWITCH B: disk=%u FAIL invalid 1.44MB FAT12 (previous retained)\n",selected);
        fflush(stdout);
        return false;
    }
    /* Commit only after validation; sector reads always use bb_b_current. */
    if(bb_b_open)(void)f_close(bb_b_current);
    bb_b_current=candidate;
    bb_b_open=true;
    bb_b_number=selected;
    if(bb_sd_dos622_active())bb622_swap_b_changed=true;
    ++bb_b_media_generation;
    printf("[bb-sd-b] LIVE SWITCH B: disk=%u OK generation=%lu\n",
           selected,(unsigned long)bb_b_media_generation);
    fflush(stdout);
    return true;
}
'''

# Emit no unsupported IRQ tricks: preserve the existing one-shot BIOS AH16
# semantics and expose whether the DOS kernel actually asks for media change.
NEW_B_AH16=r'''    if(fn==0x16u) {
        bool changed=bb_sd_dos622_take_b_change();
        static unsigned bb622_b_change_checks;
        if(changed || ++bb622_b_change_checks<=12u) {
            printf("[bb622-bmedia] AH=16 DL=01 change=%u result=%02X\n",
                   (unsigned)changed,changed?0x06u:0u);
            fflush(stdout);
        }
        bb622_status(c,changed?0x06u:0u,0u);
        return true;
    }'''

def sdboot_patch(b:bytes)->bytes:
    s,e,bom=prev.parse(b)
    if TAG in s:raise ValueError('B source already modified')
    s=prev.one(s,'static FIL bb_b_img;',
      '''static FIL bb_b_img;
/* BB622_DESCENT_SWAP_V1: two slots, commit new file only after validation. */
static FIL bb_b_swap_alt;
static FIL *bb_b_current=&bb_b_img;
static unsigned long bb_b_media_generation;
static unsigned long bb_b_reported_read_generation;''','B FIL slots')
    s=prev.one(s,'    bb_b_open = false;\n    bb622_swap_b_changed=false;',
      '    bb_b_open = false;\n    bb_b_current=&bb_b_img;bb_b_media_generation=0u;bb_b_reported_read_generation=0u;\n    bb622_swap_b_changed=false;','B cold init')
    s=prev.one(s,'    if (bb_generic_b_open) return bb_sd_b_read_generic(sector,data,size);',
      '    if (bb_generic_b_open && !bb_sd_dos622_active()) return bb_sd_b_read_generic(sector,data,size);','DOS6 B physical precedence')
    s=prev.one(s,'fr = f_lseek(&bb_b_img, (FSIZE_t)sector * 512u);',
      'fr = f_lseek(bb_b_current, (FSIZE_t)sector * 512u);','B current seek')
    s=prev.one(s,'fr=f_read(&bb_b_img, data, 512u, &got);',
      'fr=f_read(bb_b_current, data, 512u, &got);','B current read')
    s=prev.one(s,'    if (++reads <= 6u)',
      '''    if(bb_sd_dos622_active() && bb_b_media_generation &&
       bb_b_media_generation!=bb_b_reported_read_generation){
        bb_b_reported_read_generation=bb_b_media_generation;
        printf("[bb622-bmedia] B first new-image read disk=%u lba=%lu generation=%lu\\n",
               bb_b_number,(unsigned long)sector,bb_b_media_generation);
        fflush(stdout);
    }
    if (++reads <= 6u)''','post-swap sector read trace')
    b_eject=re.search(r'bool bb_sd_dos622_eject_b\(void\)\n\{.*?\n\}',s,re.S)
    if not b_eject:raise ValueError('Missing B eject function')
    block=prev.one(b_eject.group(0),'(void)f_close(&bb_b_img);',
        '(void)f_close(bb_b_current);','B eject closes active slot')
    s=s[:b_eject.start()]+block+s[b_eject.end():]
    # Only the one B selector is replaced, preserving DOS2 generic controls.
    rg=re.compile(r'bool bb_sd_b_select\(unsigned selected\)\n\{.*?\n\}\n(?=\n/\* BB_GENERIC_DISK_V1:)',re.S)
    found=list(rg.finditer(s))
    if len(found)!=1:raise ValueError(f'B selector expected exactly once, found {len(found)}')
    s=s[:found[0].start()]+NEW_B_SELECT.rstrip('\n')+s[found[0].end():]
    return prev.pack(s,e,bom)

def bios_patch(b:bytes)->bytes:
    s,e,bom=prev.parse(b)
    if TAG in s:raise ValueError('BIOS already modified')
    s=prev.one(s,'    if(fn==0x16u) {bb622_status(c,bb_sd_dos622_take_b_change()?0x06u:0u,0u);return true;}',
               NEW_B_AH16,'B BIOS AH16 diagnostic')
    return prev.pack(s,e,bom)

HOST_MENU=r'''                    # BB622_DESCENT_SWAP_V1: Alt+G / Ctrl+G compact picker.
                    # Defaults to B: for Descent, 0 ejects, Enter commits.
                    # A/B can optionally be typed before the disk number.
                    $bbDesAlt = ($k.Key -eq [ConsoleKey]::G -and
                        (($k.Modifiers -band [ConsoleModifiers]::Alt) -ne 0))
                    $bbDesCtrl = ([int][char]$k.KeyChar -eq 7)
                    if ($bbDesAlt -or $bbDesCtrl) {
                        $bbDesStage=1; $bbDesDrive='B'; $bbDesDigit=''
                        try { [Console]::Title='Alt+G floppy | B: disk 0..5 (0=eject), A/B drive, Enter confirms' } catch {}
                        continue
                    }
                    if ($bbDesStage -ne 0) {
                        if ($k.Key -eq [ConsoleKey]::Escape) {
                            $bbDesStage=0; $bbDesDigit=''
                            try { [Console]::Title='Floppy choice cancelled' } catch {}
                            continue
                        }
                        if ($k.KeyChar -eq 'a' -or $k.KeyChar -eq 'A' -or
                            $k.KeyChar -eq 'b' -or $k.KeyChar -eq 'B') {
                            $bbDesDrive=([string]$k.KeyChar).ToUpperInvariant();$bbDesDigit=''
                            try { [Console]::Title="Alt+G floppy | $($bbDesDrive): choose disk (0=eject), then Enter" } catch {}
                            continue
                        }
                        if ($k.KeyChar -ge '0' -and $k.KeyChar -le '9') {
                            $wanted=[int]([string]$k.KeyChar)
                            if ($bbDesDrive -eq 'B' -and $wanted -gt 5) {
                                $bbDesDigit=''
                                try { [Console]::Title='B: only disk 0 (eject) or disks 1..5; retry' } catch {}
                            } else {
                                $bbDesDigit=[string]$k.KeyChar
                                try { [Console]::Title="Alt+G floppy | $($bbDesDrive):$bbDesDigit ready; ENTER to apply (Esc cancels)" } catch {}
                            }
                            continue
                        }
                        if ($k.Key -eq [ConsoleKey]::Enter) {
                            if ($bbDesDigit -ne '') {
                                $bbDesCode=$bbDesDrive+$bbDesDigit
                                $serial.Write(([string][char]0x1C)+$bbDesCode)
                                [System.IO.File]::AppendAllText($log,"[bb622-altg] SENT $bbDesCode waiting for firmware response`n")
                                try { [Console]::Title="blitzBUS $bbDesCode sent | wait for [bb622-swap] OK before DOS Enter" } catch {}
                                $bbDesStage=0;$bbDesDigit=''
                            }
                            continue
                        }
                        # While selecting a disk, don't accidentally type into DOS.
                        continue
                    }
'''

def host_patch(b:bytes)->bytes:
    s,e,bom=prev.parse(b)
    if 'BB_DOS622_BOOT_EJECT_V1' not in s or '$bb622SwapStage' not in s:
        raise ValueError('expected working C-boot/eject color runner with F9 menu')
    if TAG in s:raise ValueError('host already modified')
    s=prev.one(s,"$quit=$false\n$bb622SwapStage=0\n$bb622SwapDrive=\"\"",
      "$quit=$false\n$bb622SwapStage=0\n$bb622SwapDrive=\"\"\n$bbDesStage=0\n$bbDesDrive='B'\n$bbDesDigit=''",'host new picker state')
    s=prev.one(s,'                    $k=[Console]::ReadKey($true)',
      '                    $k=[Console]::ReadKey($true)\n'+HOST_MENU.rstrip('\n'),'host Alt+G key interceptor')
    s=prev.one(s,'bb_dos622_swap_color_host.ps1','bb622_descent_color_host.ps1','new host helper')
    return prev.pack(s,e,bom)

def helper_patch(b:bytes)->bytes:
    s,e,bom=prev.parse(b)
    a="        if ($script:bb622SwapStage -eq 1) {"
    if a not in s:
        raise ValueError('Expected V2 swap-colored helper title block not found')
    s=prev.one(s,a,"        if ($script:bbDesStage -ne 0) {\n            [Console]::Title=\"Alt+G floppy $($script:bbDesDrive):$($script:bbDesDigit) | disk 0 eject | Enter commits | Esc cancels\"\n        } elseif ($script:bb622SwapStage -eq 1) {",'preserve Alt+G title')
    return prev.pack(s,e,bom)

SOURCES={SDB:sdboot_patch,BIOS:bios_patch}

def prepare(root:Path=ROOT,verbose:bool=True):
    if (root/STATE).exists():raise ValueError('Already installed; use verify/restore')
    mp=root/'.bb_dos622_boot_eject_v1_state'/'manifest.json'
    if not mp.is_file():raise ValueError('C-boot/eject V1 state missing; do not stack on an unknown firmware')
    manifest=json.loads(mp.read_bytes())
    if manifest.get('tag')!='BB_DOS622_BOOT_EJECT_V1':raise ValueError('Unexpected C-boot predecessor')
    if not (root/BASE).is_file() or not (root/OLD_HELPER).is_file() or (root/RUN).exists() or (root/HELPER).exists():
        raise ValueError('Missing original boot/eject/color runner or output runner already exists')
    old=(root/BASE).read_bytes()
    row=next((f for f in manifest['files'] if f['path']==BASE),None)
    if row is None or SHA(old)!=row['installed']:
        raise ValueError('Existing boot/eject runner differs from installed checksum')
    changes={}
    for path,transform in SOURCES.items():
        old_src=(root/path).read_bytes()
        if b'BB_DOS622_BOOT_EJECT_V1' not in old_src:
            raise ValueError(f'Boot/eject firmware marker missing: {path}')
        changes[path]=(old_src,transform(old_src))
    helper_raw=(root/OLD_HELPER).read_bytes()
    color_manifest=root/'.bb_dos622_swap_lcd_v2_state'/'manifest.json'
    if not color_manifest.is_file():raise ValueError('Missing V2 color manifest')
    cm=json.loads(color_manifest.read_bytes())
    hrow=next((f for f in cm['files'] if f['path']==OLD_HELPER),None)
    if hrow is None or SHA(helper_raw)!=hrow['installed']:
        raise ValueError('Color host helper differs from installed checksum')
    changes[RUN]=(None,host_patch(old))
    changes[HELPER]=(None,helper_patch(helper_raw))
    metadata=prev.parent.cascade(root,{p:v for p,v in changes.items() if v[0] is not None})
    if set(metadata)&set(changes):raise ValueError('Metadata cascade overlaps a source file')
    changes.update(metadata)
    if verbose:
        print(f'PROBE PASS: {len(SOURCES)} firmware sources, 2 new Alt+G host files, {len(metadata)} checksum records; no changes')
    return changes

def atomic(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.bb622-descent-new')
    try:tmp.write_bytes(data);os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def verify(root:Path=ROOT):
    mfile=root/STATE/'manifest.json'
    if not mfile.is_file():raise ValueError('Missing new install state')
    m=json.loads(mfile.read_bytes())
    if m.get('tag')!=TAG:raise ValueError('Wrong install state')
    for record in m['files']:
        name=record['path'];p=root/name
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe install path')
        if not p.is_file() or SHA(p.read_bytes())!=record['installed']:
            raise ValueError('Installed file checksum mismatch: '+name)
        if record['original'] is not None:
            saved=root/STATE/record['backup']
            if not saved.is_file() or SHA(saved.read_bytes())!=record['original']:
                raise ValueError('Backup checksum mismatch: '+name)
    print(f"VERIFY PASS: {len(m['files'])} new source/host/metadata entries and byte-exact backups")

def apply(root:Path=ROOT):
    changes=prepare(root)
    st=root/STATE;st.mkdir();touched=[];rows=[]
    try:
        for i,(rel,(old,new)) in enumerate(changes.items()):
            backup=None
            if old is not None:
                backup=f'backup_{i:03d}.bin';atomic(st/backup,old)
            rows.append({'path':rel,'backup':backup,'original':SHA(old) if old is not None else None,'installed':SHA(new)})
        atomic(st/'manifest.json',(json.dumps({'tag':TAG,'files':rows},indent=2)+'\n').encode())
        for rel,(old,new) in changes.items():atomic(root/rel,new);touched.append(rel)
        verify(root)
    except BaseException:
        for rel in reversed(touched):
            old=changes[rel][0]
            if old is None:(root/rel).unlink(missing_ok=True)
            else:atomic(root/rel,old)
        shutil.rmtree(st,ignore_errors=True)
        raise
    print('APPLIED: transactional B: switching, BIOS media trace, Alt+G menu; HDD untouched')

def restore(root:Path=ROOT):
    verify(root)
    m=json.loads((root/STATE/'manifest.json').read_bytes())
    for record in reversed(m['files']):
        q=root/record['path']
        if record['original'] is None:q.unlink()
        else:atomic(q,(root/STATE/record['backup']).read_bytes())
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: source, runner, metadata restored byte-exactly')

def selftest():
    # Source fragments intentionally have one and only one of each expected anchor.
    source=r'''static FIL bb_b_img;
    bb_b_open = false;
    bb622_swap_b_changed=false;
    if (bb_generic_b_open) return bb_sd_b_read_generic(sector,data,size);
    fr = f_lseek(&bb_b_img, (FSIZE_t)sector * 512u);
    if (fr == FR_OK) fr=f_read(&bb_b_img, data, 512u, &got);
    (void)f_close(&bb_b_img);
        bb_b_open=false;
    if (++reads <= 6u)
/* BB_DOS622_BOOT_EJECT_V1: B eject */
bool bb_sd_b_select(unsigned selected)
{
    return true;
}

/* BB_GENERIC_DISK_V1: */
'''
    source=source.replace('/* BB_DOS622_BOOT_EJECT_V1: B eject */',prev.B_EJECT.rstrip())
    bios='''/* BB_DOS622_BOOT_EJECT_V1 */
    if(fn==0x16u) {bb622_status(c,bb_sd_dos622_take_b_change()?0x06u:0u,0u);return true;}
'''
    helper="""# BB_DOS622_SWAP_LCD_V2
        if ($script:bb622SwapStage -eq 1) {
"""
    host="""# BB_DOS622_BOOT_EJECT_V1
$quit=$false
$bb622SwapStage=0
$bb622SwapDrive=""
. (Join-Path $PSScriptRoot 'bb_dos622_swap_color_host.ps1')
                    $k=[Console]::ReadKey($true)
"""
    for ending in ('\n','\r\n'):
        for raw,fn in [(source.encode(),sdboot_patch),(bios.encode(),bios_patch),(host.encode(),host_patch),(helper.encode(),helper_patch)]:
            inb=raw.replace(b'\n',ending.encode())
            out=fn(inb);_,sep,_=prev.parse(out)
            assert sep==ending
        h=host_patch(host.replace('\n',ending).encode()).decode()
        for needle in ['ConsoleModifiers]::Alt','[char]$k.KeyChar -eq 7','BB622_DESCENT_SWAP_V1','0=eject','Enter','[ConsoleKey]::Enter']:
            assert needle in h,needle
    # Full isolated transaction including restoration; cascade mocked ONLY in fixture.
    cascade=prev.parent.cascade
    try:
        prev.parent.cascade=lambda root,updates:{}
        for ending in ('\n','\r\n'):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d)
                for name,data in [(SDB,source),(BIOS,bios),(BASE,host),(OLD_HELPER,helper)]:
                    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
                    p.write_bytes(data.replace('\n',ending).encode())
                st=root/'.bb_dos622_boot_eject_v1_state';st.mkdir()
                raw=(root/BASE).read_bytes()
                (st/'manifest.json').write_text(json.dumps({'tag':'BB_DOS622_BOOT_EJECT_V1','files':[{'path':BASE,'installed':SHA(raw)}]}))
                mcolor=root/'.bb_dos622_swap_lcd_v2_state';mcolor.mkdir()
                hraw=(root/OLD_HELPER).read_bytes()
                (mcolor/'manifest.json').write_text(json.dumps({'files':[{'path':OLD_HELPER,'installed':SHA(hraw)}]}))
                baseline={(root/name).read_bytes():name for name in (SDB,BIOS,BASE,OLD_HELPER)}
                assert len(prepare(root,False))==4
                apply(root);verify(root);restore(root)
                for raw,name in baseline.items():assert (root/name).read_bytes()==raw
                assert not (root/RUN).exists() and not (root/HELPER).exists() and not (root/STATE).exists()
    finally:prev.parent.cascade=cascade
    print('SELFTEST PASS LF/CRLF, Alt+G/0, full install/restore with exact backups (Pico not tested)')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    cmd=p.parse_args().action
    try:
        {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore}[cmd]()
    except (ValueError,OSError,AssertionError,KeyError,ImportError) as exc:
        print('ERROR:',exc,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
