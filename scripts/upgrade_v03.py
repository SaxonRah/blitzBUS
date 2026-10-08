"""Update the installed blitzBUS LCD bridge to v0.3; leave microDOS untouched."""
from pathlib import Path
import argparse,shutil,sys
p=argparse.ArgumentParser();p.add_argument('--microdos',default=r'C:\microDOS');a=p.parse_args()
root=Path(__file__).resolve().parents[1];new=root/'src/bb_lcd_console.c';target=Path(a.microdos)/'blitzbus-overlay/bb_lcd_console.c'
source=Path(a.microdos)/'pico/microdos_pico.c'
if not source.exists() or 'BLITZBUS_LCD_CONSOLE' not in source.read_text(encoding='utf-8'):
    sys.exit('ERROR: blitzBUS v0.2 overlay is not enabled. Nothing changed.')
if not target.exists():sys.exit('ERROR: installed LCD bridge not found. Nothing changed.')
old=target.read_text(encoding='utf-8');newtext=new.read_text(encoding='utf-8')
if 'static mr_pico_ili9341_t lcd;' not in old and 'LCD SPI init begin' not in old:
    sys.exit('ERROR: unrecognized modified LCD bridge; nothing changed.')
backup=root/'backups/bb_lcd_console.pre-v03.c';backup.parent.mkdir(parents=True,exist_ok=True)
if not backup.exists():shutil.copy2(target,backup)
if old!=newtext:
    shutil.copy2(new,target)
    print('UPDATED',target)
else:print('ALREADY UPDATED',target)
print('BACKUP',backup)
print('NEXT: bb.bat run -Port COM5 -Seconds 180 -AutoDos2Test')
