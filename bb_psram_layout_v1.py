#!/usr/bin/env python3
"""Reversible blitzBUS PSRAM input-subsection ordering experiment.

Changes only scripts/install_live.py, the generator responsible for bb_microdos_pico.c.
No patch to generated CMake files, SDK, emulator, or linker script.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import re

TAG = 'BB_PSRAM_LAYOUT_DISK_AFTER_GUEST_V1'
ROOT_DEFAULT = r'C:\blitzBUS'
BEFORE = "    pico_text='#include \"bb_live.h\"\\n'+pico_text"
INJECT = (
    BEFORE + '\n'
    '    # '+TAG+': preserve all allocations; sort disk subsection after aligned guest.\n'
    '    # The normal loader still creates a 360 KiB g_disk and guest is unchanged.\n'
    '    _disk_decl = \'__uninitialized_psram("md_disk")\'\n'
    '    if pico_text.count(_disk_decl) != 1:\n'
    '        raise SystemExit("'+TAG+': expected one disk PSRAM declaration")\n'
    '    pico_text = pico_text.replace(_disk_decl, \'__uninitialized_psram("zz_md_disk")\', 1)'
)

def do_action(root, mode):
    target = root / 'scripts' / 'install_live.py'
    backup = target.with_name(target.name+'.psram-layout-v1.bak')
    if not target.is_file():
        raise SystemExit(f'Missing: {target}')
    current = target.read_text(encoding='utf-8')
    if mode == 'apply':
        if TAG in current:
            print('Already applied:', target)
            return
        if current.count(BEFORE) != 1:
            raise SystemExit('Installer anchor changed or ambiguous; NO FILES CHANGED.')
        if backup.exists():
            if TAG in backup.read_text(encoding='utf-8'):
                raise SystemExit('Backup contains previous experiment, refusing.')
            print('Using existing untouched backup:', backup)
        else:
            shutil.copy2(target, backup)
        amended = current.replace(BEFORE, INJECT, 1)
        compile(amended, str(target), 'exec')
        target.write_text(amended, encoding='utf-8')
        print('Installed PSRAM disk subsection ordering experiment:', target)
        print('Backup:', backup)
        print('Next run bb_live_run.ps1; this installer regenerates the DOS source.')
    elif mode == 'restore':
        if TAG not in current:
            print('Not installed; leaving file unchanged.')
            return
        if current.count(INJECT) != 1:
            raise SystemExit('Installed block differs from expected; refusing to overwrite local edits.')
        updated=current.replace(INJECT, BEFORE, 1)
        compile(updated, str(target), 'exec')
        target.write_text(updated,encoding='utf-8')
        print('Removed experiment only; other installer changes preserved:',target)
        print('Rebuild/reflash to restore firmware.')
    else:
        print('Installer:', 'EXPERIMENT APPLIED' if TAG in current else 'baseline/no experiment')
        source=root/'generated'/'bb_microdos_pico.c'
        if source.exists():
            t=source.read_text(encoding='utf-8')
            print('Generated disk subsection:', 'zz_md_disk' if '__uninitialized_psram("zz_md_disk")' in t else ('md_disk' if '__uninitialized_psram("md_disk")' in t else 'NOT FOUND'))
        else: print('Generated source missing:',source)

def inspect(elf, toolbin):
    exe=toolbin / ('arm-none-eabi-nm.exe' if __import__('os').name=='nt' else 'arm-none-eabi-nm')
    if not exe.exists(): raise SystemExit(f'Missing {exe}')
    if not elf.exists(): raise SystemExit(f'Missing {elf}')
    p=subprocess.run([str(exe),'-S','-n',str(elf)],capture_output=True,text=True,check=True)
    targets=('bb_meta','bb_shadow_buf','g_guest_raw','g_disk')
    data={}
    for line in p.stdout.splitlines():
        parts=line.split()
        if len(parts)==4 and parts[3] in targets:
            data[parts[3]]=(int(parts[0],16),int(parts[1],16))
    for name in targets:
        if name not in data: print(f'{name:14} not found'); continue
        addr,size=data[name]; print(f'{name:14} 0x{addr:08X}  size={size:9,d} bytes')
    if 'g_guest_raw' in data and 'g_disk' in data:
        guest,gs=data['g_guest_raw'];disk,ds=data['g_disk']
        print('Guest on 2MiB boundary:',guest % (2*1024*1024)==0)
        print('Disk after guest:',disk>=guest+gs)
        print('Guest desired position:',guest==0x11200000)
        if disk>=guest+gs and guest==0x11200000:
            print('LAYOUT TEST PASSED: verify runtime boot, T2E, 3DBench and cache coherency before keeping.')
        else:
            print('Layout not as targeted; restore experiment unless there is another verified benefit.')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=['apply','restore','status','inspect'])
    ap.add_argument('--root',default=ROOT_DEFAULT)
    ap.add_argument('--elf',default=r'C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.elf')
    ap.add_argument('--toolbin',default=r'C:\Users\Jupiter\.pico-sdk\toolchain\14_2_Rel1\bin')
    args=ap.parse_args()
    if args.mode=='inspect': inspect(Path(args.elf),Path(args.toolbin))
    else:do_action(Path(args.root),args.mode)
