"""Create a reversible microDOS -> blitzBUS LCD overlay. No git patches."""
import argparse
import pathlib
import shutil
import sys

ap=argparse.ArgumentParser()
ap.add_argument('--microdos',default=r'C:\microDOS')
ap.add_argument('--render',default=r'C:\microrender')
ap.add_argument('--restore',action='store_true')
a=ap.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
md=pathlib.Path(a.microdos)
mr=pathlib.Path(a.render)
source=md/'pico/microdos_pico.c'
cmake=md/'pico/CMakeLists.txt'
backup=root/'backups'
anchor='#include "pico/stdlib.h"'
write_anchor='    stdio_flush();\n    g_perf.console_out_us += time_us_64() - t0;'
startup_anchor='    memset(g_guest,0,MD_GUEST_BYTES); memcpy(g_disk,md_blob_disk,MD_DISK_BYTES);'
cmake_anchor='    if(cache OR kernel_aot OR app_aot)'
cmake_insert='''    # blitzBUS owner: optional Pico 4-inch LCD text console (COM input unchanged)\n    if(target STREQUAL "microdos_pico")\n        target_sources(${target} PRIVATE\n            "${CMAKE_CURRENT_LIST_DIR}/../blitzbus-overlay/bb_lcd_console.c"\n            "${CMAKE_CURRENT_LIST_DIR}/../blitzbus-overlay/mr_pico_ili9341.c"\n            "${CMAKE_CURRENT_LIST_DIR}/../blitzbus-overlay/gfx_font5x7.c")\n        target_include_directories(${target} PRIVATE\n            "${CMAKE_CURRENT_LIST_DIR}/../blitzbus-overlay")\n        target_compile_definitions(${target} PRIVATE\n            MR_LCD_PANEL_ST7796S=1 MR_LCD_SPI_BAUD=40000000u)\n        target_link_libraries(${target} PRIVATE hardware_spi hardware_dma)\n    endif()\n'''
files=[source,cmake]
if a.restore:
    for f in files:
        bak=backup/(f.name+'.original')
        if not bak.exists():raise SystemExit('Missing backup: '+str(bak))
        shutil.copy2(bak,f);print('RESTORED',f)
    print('Original microDOS sources restored; overlay directory may be deleted.')
    sys.exit(0)
for f in files:
    if not f.is_file():raise SystemExit('Not found: '+str(f))
if not (mr/'shared/rp2350/mr_pico_ili9341.c').is_file():raise SystemExit('MicroRender source missing')
text=source.read_text(encoding='utf-8')
cm=cmake.read_text(encoding='utf-8')
if '#include "bb_lcd_console.h"' in text and '# blitzBUS owner:' in cm:
    print('Already installed; no changes.');sys.exit(0)
for label,content,needle in [('include',text,anchor),('console write',text,write_anchor),('init',text,startup_anchor),('cmake',cm,cmake_anchor)]:
    if content.count(needle)!=1:raise SystemExit(f'Expected one {label} anchor; found {content.count(needle)}. Nothing changed.')
if '#include "bb_lcd_console.h"' in text or '# blitzBUS owner:' in cm:raise SystemExit('Partial overlay detected; stop and inspect sources')
new_text=text.replace(anchor,anchor+'\n#include "bb_lcd_console.h"',1)
new_text=new_text.replace(write_anchor,'    bb_lcd_console_write(data, size);\n    bb_lcd_console_flush();\n'+write_anchor,1)
new_text=new_text.replace(startup_anchor,'    bb_lcd_console_init();\n'+startup_anchor,1)
new_cmake=cm.replace(cmake_anchor,cmake_insert+'\n'+cmake_anchor,1)
backup.mkdir(exist_ok=True)
for f in files:
    b=backup/(f.name+'.original')
    if not b.exists():shutil.copy2(f,b)
out=md/'blitzbus-overlay'
out.mkdir(exist_ok=True)
for f in ['bb_lcd_console.c','bb_lcd_console.h']:
    shutil.copy2(root/'src'/f,out/f)
for f in ['mr_pico_ili9341.c','mr_pico_ili9341.h']:
    shutil.copy2(mr/'shared/rp2350'/f,out/f)
shutil.copy2(mr/'shared/src/gfx_font5x7.c',out/'gfx_font5x7.c')
shutil.copy2(mr/'shared/src/gfx_font5x7.h',out/'gfx_font5x7.h')
# gfx font includes gfx.h; use actual headers, not placeholders
for f in mr.joinpath('shared/src').glob('gfx*.h'):
    shutil.copy2(f,out/f.name)
source.write_text(new_text,encoding='utf-8',newline='')
cmake.write_text(new_cmake,encoding='utf-8',newline='')
print('INSTALLED blitzBUS text LCD overlay')
print('Source:',source)
print('CMake:',cmake)
print('Backup:',backup)
