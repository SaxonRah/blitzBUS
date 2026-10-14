#!/usr/bin/env python3
"""Hermetic C11 unit test for BB622_DESCENT_SWAP_V1 transactional B: selector.

Fix for Windows Clang accidentally including Open Watcom headers from C:\\WATCOM\\H.
No user source/firmware/image is written. Requires a usable gcc or clang compiler.
Use: python bb622_descent_swap_c11_v2.py [--cc /path/to/clang]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from bb622_descent_swap_v1 import NEW_B_SELECT
except ImportError as exc:
    raise SystemExit('ERROR: copy this test beside bb622_descent_swap_v1.py: ' + str(exc))

# The C fixture deliberately has no #include directives, and -nostdinc
# prevents compiler search paths from injecting an incompatible C runtime.
# GCC/Clang provide __SIZE_TYPE__ and __UINT8_TYPE__; printf/sscanf/etc.
# still link to the normal runtime selected by the compiler driver.
PRE = r'''/* Hermetic C11 header-free unit test of real firmware selector. */
typedef _Bool bool;
#define true 1
#define false 0
typedef __UINT8_TYPE__ uint8_t;
typedef __SIZE_TYPE__ size_t;
extern int printf(const char*, ...);
extern int sscanf(const char*, const char*, ...);
extern int snprintf(char*, size_t, const char*, ...);
extern int puts(const char*);
extern int fflush(void*);
extern void *memset(void*, int, size_t);
extern void abort(void);
#define stdout ((void*)0) /* fflush(NULL) flushes all streams */
#define assert(expr) do { if (!(expr)) { \
    printf("ASSERT FAILED line %d: %s\n", __LINE__, #expr); \
    fflush((void*)0); abort(); \
} } while (0)
typedef struct{unsigned disk,pos;bool open;}FIL;
typedef int FRESULT;
typedef unsigned UINT;
#define FR_OK 0
#define FA_READ 1
static FIL bb_b_img={1,0,true};
static FIL bb_b_swap_alt={0,0,false};
static FIL *bb_b_current=&bb_b_img;
static bool bb_b_open=true,bb_img_open=true,bb622_swap_b_changed=false;
static unsigned bb_b_number=1;
static unsigned long bb_b_media_generation;
static unsigned closes,reads;
static bool corrupt_size;
static unsigned fake_spi;
#define spi1 (&fake_spi)
static unsigned spi_set_baudrate(unsigned* p,unsigned n){(void)p;return n;}
static bool bb_sd_dos622_active(void){return true;}
static int f_open(FIL*f,const char *name,unsigned mode){
  unsigned n=0;
  (void)mode;
  if(sscanf(name,"0:/BLITZBUS/DESCENT%u.IMG",&n)!=1 || n==4) return 4;
  f->disk=n;f->open=true;f->pos=0;
  return FR_OK;
}
static unsigned f_size(FIL*f){return (corrupt_size && f->disk==3)?1024u:1474560u;}
static int f_close(FIL*f){assert(f->open);f->open=false;closes++;return FR_OK;}
static int f_read(FIL*f,void*buf,unsigned n,UINT*got){
 uint8_t *p=(uint8_t*)buf;
 assert(f->open && n==512);
 memset(buf,0,n);
 p[0]=0xEB;p[11]=0;p[12]=2;p[13]=1;p[16]=2;
 p[19]=0x40;p[20]=0x0B;p[510]=0x55;p[511]=0xAA;
 if(f->disk==5)p[510]=0;
 f->pos+=n;*got=n;reads++;return FR_OK;
}
'''
POST = r'''
static bool eject_b(void){
 if(bb_b_open){(void)f_close(bb_b_current);bb_b_open=false;}
 bb_b_number=0;bb622_swap_b_changed=true;return true;
}
int main(void){
  assert(bb_sd_b_select(2));
  assert(bb_b_open && bb_b_current==&bb_b_swap_alt);
  assert(!bb_b_img.open && bb_b_swap_alt.open && bb_b_number==2);
  assert(bb622_swap_b_changed && bb_b_media_generation==1 && closes==1);
  bb622_swap_b_changed=false;
  assert(bb_sd_b_select(2));
  assert(!bb622_swap_b_changed && closes==1);
  assert(!bb_sd_b_select(4));
  assert(bb_b_current==&bb_b_swap_alt && bb_b_swap_alt.open && closes==1);
  assert(!bb622_swap_b_changed);
  assert(!bb_sd_b_select(5));
  assert(bb_b_swap_alt.open && bb_b_number==2 && closes==2);
  assert(!bb622_swap_b_changed);
  corrupt_size=true;
  assert(!bb_sd_b_select(3));
  assert(bb_b_swap_alt.open && bb_b_number==2 && closes==3);
  corrupt_size=false;
  assert(bb_sd_b_select(3));
  assert(bb_b_current==&bb_b_img && bb_b_number==3 && bb_b_img.open && closes==4);
  assert(eject_b() && !bb_b_img.open && bb_b_number==0);
  assert(bb_sd_b_select(1));
  assert(bb_b_swap_alt.open && bb_b_current==&bb_b_swap_alt && bb_b_number==1);
  puts("C11 PASS: B: transactional swap, missing/invalid image, eject/reinsert, generation and flags");
  return 0;
}
'''

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cc', help='path or command name for a GCC/Clang C compiler')
    args = ap.parse_args()
    cc = args.cc or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        print('ERROR: no gcc/clang compiler found; run from Developer PowerShell or provide --cc PATH')
        return 2
    # Don't invoke any compiler auto-probe that depends on the C include path.
    print('Compiler:', cc)
    print('Include isolation: -nostdinc, no WATCOM/SDK headers imported')
    with tempfile.TemporaryDirectory(prefix='bb622_bmedia_') as d:
        td = Path(d)
        src = td / 'bmedia.c'
        exe = td / ('bmedia.exe' if os.name == 'nt' else 'bmedia')
        src.write_bytes((PRE + NEW_B_SELECT + POST).encode('utf-8'))
        argv = [cc, '-std=c11', '-nostdinc', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-function', str(src), '-o', str(exe)]
        try:
            build = subprocess.run(argv, capture_output=True, text=True, timeout=40)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print('ERROR: host compiler execution failed:', exc)
            return 2
        if build.returncode != 0:
            print('C11 compile FAILED (not a Pico firmware result):\n' + build.stderr)
            return 1
        try:
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print('ERROR: compiled harness execution failed:', exc)
            return 2
        if run.returncode != 0:
            print('C11 runtime FAILED, exit code %d:\n%s\n%s' %
                  (run.returncode, run.stdout, run.stderr))
            return 1
        print(run.stdout.strip())
        print('PASS: original project firmware/SD/HDD/lineage files were not modified')
    return 0

if __name__ == '__main__':
    sys.exit(main())
