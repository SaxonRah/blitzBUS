"""Upgrade existing v0.2/v0.3 LCD overlay to 480x200 DOS + 480x120 dashboard.
This is deliberately a narrow, reversible update, not a Git patch.
"""
from pathlib import Path
import argparse,shutil,sys
p=argparse.ArgumentParser();p.add_argument('--microdos',default=r'C:\microDOS');a=p.parse_args()
root=Path(__file__).resolve().parents[1];md=Path(a.microdos)
source=md/'pico/microdos_pico.c'; cmake=md/'pico/CMakeLists.txt'
installed=md/'blitzbus-overlay/bb_lcd_console.c'; new=root/'src/bb_lcd_console.c'
for file in [source,cmake,installed,new]:
    if not file.is_file():sys.exit(f'ERROR: missing {file}; nothing changed')
s=source.read_text(encoding='utf-8');c=cmake.read_text(encoding='utf-8');old=installed.read_text(encoding='utf-8')
if 'BLITZBUS_LCD_CONSOLE' not in s or '# blitzBUS owner:' not in c or 'mr_pico_ili9341_init' not in old:
    sys.exit('ERROR: unfamiliar overlay; nothing changed')
if 'MR_LCD_PANEL_ST7796S=1 MR_LCD_SPI_BAUD=40000000u' not in c:
    sys.exit('ERROR: expected CMake LCD compile definition not found; nothing changed')
backup=root/'backups'/'pre-v04';backup.mkdir(parents=True,exist_ok=True)
for file in [cmake,installed]:
    bak=backup/file.name
    if not bak.exists():shutil.copy2(file,bak)
c2=c.replace('MR_LCD_PANEL_ST7796S=1 MR_LCD_SPI_BAUD=40000000u','MR_LCD_PANEL_ST7796S=1 MR_ILI9341_MADCTL=0xE8 MR_LCD_SPI_BAUD=40000000u',1)
shutil.copy2(new,installed)
cmake.write_text(c2,encoding='utf-8',newline='')
print('UPGRADED: ST7796 MADCTL=0xE8, 80x25 console, 480x120 dashboard')
print('UPDATED',installed);print('UPDATED',cmake);print('BACKUPS',backup)
print('NEXT: bb.bat run -Port COM5 -Seconds 180 -AutoDos2Test')
