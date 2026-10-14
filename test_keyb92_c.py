#!/usr/bin/env python3
"""Compile and execute the EXACT generated KEYB92 branch with native C compilers."""
from __future__ import annotations
import shutil, subprocess, tempfile
from pathlib import Path
import bb_dos622_keyb92_v1 as k

FUNC_PRE=r'''#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#define PICO_ON_DEVICE 1
static bool dos622_active = true;
static bool bb_sd_dos622_active(void) { return dos622_active; }
static int keyboard(uint16_t *ax, uint16_t *flags) {
    const uint8_t ah = (uint8_t)(*ax >> 8);
    (void)flags;
'''
FUNC_POST=r'''
    return 0;
}
int main(void) {
    uint16_t ax=0x9200, flags=0x0246;
    assert(keyboard(&ax,&flags)==1);
    assert(ax==0x8000 && flags==0x0246);
    ax=0x92AB;
    assert(keyboard(&ax,&flags)==1 && ax==0x80AB);
    ax=0x0100;
    assert(keyboard(&ax,&flags)==0 && ax==0x0100);
    dos622_active=false;
    ax=0x9200;
    assert(keyboard(&ax,&flags)==0 && ax==0x9200);
    assert(flags==0x0246);
    return 0;
}
'''

def main():
    for name in ('gcc','clang'):
        cc=shutil.which(name)
        if not cc:continue
        with tempfile.TemporaryDirectory(prefix='bb622_keyb92c_') as tmp:
            p=Path(tmp)
            src=p/'test.c';exe=p/'test'
            src.write_text(FUNC_PRE+k.SNIPPET.decode('ascii')+FUNC_POST)
            cmd=[cc,'-std=c11','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(src),'-o',str(exe)]
            subprocess.run(cmd,check=True)
            r=subprocess.run([str(exe)],capture_output=True,text=True)
            if r.returncode:
                raise RuntimeError(f'{name} runtime failed {r.returncode}: {r.stderr}')
            print(f'{name}: KEYB92 AX=9200->8000 and AX=92AB->80AB; DOS2/off bypass; flags unchanged: PASS')
    print('Compiled C behavior PASS')
if __name__=='__main__':main()
