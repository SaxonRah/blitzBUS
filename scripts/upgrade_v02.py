"""Upgrade blitzBUS v0.1's installed microDOS overlay to target-gated v0.2.

No git patch. Exact source anchors. Leave unrelated microDOS targets untouched.
"""
from pathlib import Path
import argparse
import shutil

parser=argparse.ArgumentParser()
parser.add_argument('--microdos',default=r'C:\microDOS')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
md=Path(args.microdos)
src=md/'pico/microdos_pico.c'
cm=md/'pico/CMakeLists.txt'
files={src:src.read_text(encoding='utf-8'),cm:cm.read_text(encoding='utf-8')}
gate='#if defined(BLITZBUS_LCD_CONSOLE) && BLITZBUS_LCD_CONSOLE'
s=files[src]
c=files[cm]
if gate in s and 'BLITZBUS_LCD_CONSOLE=1' in c:
    print('ALREADY UPGRADED: LCD bridge is restricted to microdos_pico')
    raise SystemExit(0)
if s.count('#include "bb_lcd_console.h"')!=1 or c.count('# blitzBUS owner:')!=1:
    raise SystemExit('v0.1 overlay not detected. Run bb.bat install first; no changes made.')
anchors=[
    ('#include "bb_lcd_console.h"',gate+'\n#include "bb_lcd_console.h"\n#endif'),
    ('    bb_lcd_console_init();',gate+'\n    bb_lcd_console_init();\n#endif'),
    ('    bb_lcd_console_write(data, size);\n    bb_lcd_console_flush();',gate+'\n    bb_lcd_console_write(data, size);\n    bb_lcd_console_flush();\n#endif'),
]
for a,b in anchors:
    if s.count(a)!=1:raise SystemExit('Source anchor mismatch: '+a)
    s=s.replace(a,b,1)
a='        target_compile_definitions(${target} PRIVATE\n            MR_LCD_PANEL_ST7796S=1 MR_LCD_SPI_BAUD=40000000u)'
b='        target_compile_definitions(${target} PRIVATE\n            BLITZBUS_LCD_CONSOLE=1\n            MR_LCD_PANEL_ST7796S=1 MR_LCD_SPI_BAUD=40000000u)'
if c.count(a)!=1:raise SystemExit('CMake target anchor mismatch; no changes made.')
c=c.replace(a,b,1)
# Snapshot the exact v0.1 installed state before upgrading. Never overwrite it.
backup=root/'backups'/'pre-v02'
backup.mkdir(parents=True,exist_ok=True)
for path in files:
    dest=backup/path.name
    if not dest.exists():shutil.copy2(path,dest)
src.write_text(s,encoding='utf-8',newline='')
cm.write_text(c,encoding='utf-8',newline='')
print('UPGRADED blitzBUS v0.2: only microdos_pico sees LCD headers and functions')
print('SOURCE:',src)
print('CMAKE: ',cm)
print('BACKUP:',backup)
