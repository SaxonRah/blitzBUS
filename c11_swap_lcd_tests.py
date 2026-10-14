#!/usr/bin/env python3
"""Compile and run isolated C11 host contracts for DOS622 media switching and LCD VGA cells.
Does NOT claim full Pico firmware has compiled.
"""
from pathlib import Path
import tempfile,subprocess,shutil,sys
from bb_dos622_swap_lcd_v2 import SD_A_FUNC,B_MEDIA,LCD_HELPER
CC=shutil.which('gcc') or shutil.which('clang')
if not CC:raise SystemExit('No host C11 compiler present')
A=r'''#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stdlib.h>
typedef struct {unsigned disk; bool opened; unsigned pos;} FIL;
typedef int FRESULT;
typedef unsigned UINT;
#define FR_OK 0
#define FA_READ 1
static FIL bb622_disk={1,true,0};
static FIL bb622_swap_alt;
static FIL *bb622_swap_active=&bb622_disk;
static unsigned bb622_swap_a_number=1;
static bool bb622_swap_a_changed;
static bool bb622_swap_b_changed;
static bool bb622_disk_open=true;
static void bb622_retime_spi1(void){}
static int f_open(FIL *f,const char *path,int mode){
  (void)mode;
  unsigned disk=1;
  if(strstr(path,"DOS6222"))disk=2;
  if(strstr(path,"DOS6223"))disk=3;
  if(strstr(path,"DOS6224"))return 4;
  f->disk=disk;f->opened=true;f->pos=0;return 0;
}
static unsigned f_size(FIL*f){(void)f;return 1474560u;}
static int f_close(FIL*f){f->opened=false;return 0;}
static int f_read(FIL*f,void *buf,unsigned len,UINT *got){
  uint8_t *p=(uint8_t*)buf;
  if(!f->opened ||len!=512)return 1;
  memset(p,0,512);
  p[0]=0xEB;p[11]=0;p[12]=2;p[13]=1;p[14]=1;
  p[16]=2;p[17]=224;p[19]=0x40;p[20]=0x0B;
  p[22]=9;p[24]=18;p[26]=2;p[510]=0x55;p[511]=0xAA;
  *got=512;f->pos+=512;return 0;
}
'''
B=r'''
int main(void){
  assert(bb_sd_dos622_select_a(2));
  assert(bb622_swap_active==&bb622_swap_alt);
  assert(bb622_swap_a_number==2);
  assert(bb_sd_dos622_take_a_change());
  assert(!bb_sd_dos622_take_a_change());
  assert(!bb_sd_dos622_select_a(4));
  assert(bb622_swap_active==&bb622_swap_alt);
  assert(bb622_swap_active->opened);
  assert(bb_sd_dos622_select_a(1));
  assert(bb622_swap_active==&bb622_disk);
  assert(bb622_swap_a_number==1);
  assert(bb_sd_dos622_take_a_change());
  bb622_swap_b_changed=true;
  assert(bb_sd_dos622_take_b_change());
  assert(!bb_sd_dos622_take_b_change());
  puts("C11 DOS6 A/B swaps PASS (new-first, missing file retains old, media flag one-shot)");
  return 0;
}
'''
LCD_A=r'''#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#define ROWS 25
#define COLS 80
#define __uninitialized_psram(tag)
static uint8_t gfx_font5x7[96][5];
'''
LCD_B=r'''
int main(void){
   uint16_t pixels[480u*8u];
   memset(pixels,0,sizeof pixels);
   bb622_lcd_draw_cell(pixels,480,0,0xCDu,0x1Eu);
   assert(pixels[2*480+0]==0xFFE0u); /* yellow double rule */
   assert(pixels[1*480+0]==0x0015u); /* blue background */
   bb622_lcd_draw_cell(pixels,480,6,0xBAu,0x4Fu);
   assert(pixels[0*480+7]==0xFFFFu); /* white vertical */
   assert(pixels[0*480+8]==0xA800u); /* red background */
   bb622_lcd_draw_cell(pixels,480,12,'A',0x70u);
   assert(pixels[0*480+12]==0xAD55u); /* grey background, black text */
   assert(bb622_cp437_shape(0xC9u));
   assert(!bb622_cp437_shape('A'));
   puts("C11 LCD VGA colors + CP437 box cells PASS");
   return 0;
}
'''
def compile_run(label,source):
    with tempfile.TemporaryDirectory() as td:
        src=Path(td)/'test.c';exe=Path(td)/'test'
        src.write_text(source)
        p=subprocess.run([CC,'-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable',str(src),'-o',str(exe)],capture_output=True,text=True)
        if p.returncode:raise RuntimeError(f'{label} compile failed:\n'+p.stderr[:5000])
        p=subprocess.run([str(exe)],capture_output=True,text=True)
        if p.returncode:raise RuntimeError(f'{label} runtime failed:\n'+p.stdout+'\n'+p.stderr)
        print(p.stdout.strip())
compile_run('SD A/B',A+SD_A_FUNC+B_MEDIA+B)
compile_run('LCD',LCD_A+LCD_HELPER+LCD_B)
