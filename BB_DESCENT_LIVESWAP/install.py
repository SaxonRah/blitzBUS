from pathlib import Path
import argparse,shutil,subprocess,sys

def replace1(s,a,b,name):
 n=s.count(a)
 if n!=1:raise RuntimeError(f'{name}: expected one anchor, got {n}; no target changed')
 return s.replace(a,b,1)

def main():
 p=argparse.ArgumentParser(description='Stage2F: live B: disk selection from DOS DISK.COM')
 p.add_argument('--root',default=r'C:\blitzBUS');p.add_argument('--restore',action='store_true');a=p.parse_args()
 root=Path(a.root);base=Path(__file__).with_name('install_base.py');sd=root/'sd_boot'
 boot=sd/'bb_sd_boot.c';driver=sd/'bb_msdos2_boot.c'
 if a.restore:
  r=subprocess.run([sys.executable,str(base),'--root',str(root),'--restore'])
  raise SystemExit(r.returncode)
 if not boot.is_file() or not driver.is_file():raise RuntimeError('Stage2D private files missing')
 if 'BB_DESCENT_LIVESWAP_V1' in boot.read_text():
  print('Live B: swap already installed, nothing changed.');return
 if 'BB_DESCENT_VFLOPPY_B_V1' not in boot.read_text():
  subprocess.run([sys.executable,str(base),'--root',str(root)],check=True)
 sb=boot.read_text(encoding='utf-8');d=driver.read_text(encoding='utf-8')
 if 'BB_DESCENT_VFLOPPY_B_V1' not in sb or 'bb_sd_b_available' not in d:
  raise RuntimeError('Stage2F base installation missing')
 sb += r'''
/* BB_DESCENT_LIVESWAP_V1. Called only by the emulator's INT F6 service. */
bool bb_sd_b_select(unsigned selected)
{
    char path[96];
    FRESULT fr;
    unsigned previous=bb_b_number;
    if (selected < 1u || selected > 5u || !bb_img_open) return false;
    if (selected == bb_b_number && bb_b_open) return true;
    if (bb_b_open) {
        (void)f_close(&bb_b_img);
        bb_b_open=false;
    }
    if (snprintf(path, sizeof(path), "%s/BLITZBUS/DESCENT%u.IMG", "0:", selected) >= (int)sizeof(path))
        return false;
    (void)spi_set_baudrate(spi1, 12500000u);
    fr=f_open(&bb_b_img,path,FA_READ);
    if (fr==FR_OK && f_size(&bb_b_img)==(FSIZE_t)1474560u) {
        bb_b_open=true;
        bb_b_number=selected;
        printf("[bb-sd-b] LIVE SWITCH B: disk=%u OK\n",selected);
        return true;
    }
    if (fr==FR_OK) (void)f_close(&bb_b_img);
    printf("[bb-sd-b] LIVE SWITCH FAILED selected=%u fr=%d\n",selected,(int)fr);
    if (previous >= 1u && previous <= 5u) {
        if (snprintf(path,sizeof(path),"%s/BLITZBUS/DESCENT%u.IMG","0:",previous)<(int)sizeof(path) &&
            f_open(&bb_b_img,path,FA_READ)==FR_OK) {
            bb_b_open=true;
            bb_b_number=previous;
        }
    }
    return false;
}
'''
 # Multi-unit DOS block driver handles B: media changes through the standard DOS 2 device request.
 needle='''    if (vector == MD_MSDOS2_NATIVE_STRATEGY_INT) {'''
 hook='''    /* Emulator-defined INT F6: AH=B0, AL=1..5. Returns AH=0 success, AH=1 error.
       A DOS COM program on A: drives the runtime B: floppy selection. */
    if (vector == 0xF6u && ((cpu->r[MD_X86_AX] >> 8) & 0xFFu) == 0xB0u) {
        unsigned number=(unsigned)(cpu->r[MD_X86_AX] & 0xFFu);
        bool ok=bb_sd_b_select(number);
        cpu->r[MD_X86_AX]=(uint16_t)((ok ? 0u : 1u)<<8 | number);
        return true;
    }

'''
 d=replace1(d,needle,hook+needle,'INT F6 hook')
 d=replace1(d,'extern bool bb_sd_b_available(void);',
 '''extern bool bb_sd_b_select(unsigned);
extern bool bb_sd_b_available(void);''','B extern')
 # On each B media check, advise DOS to refresh the FAT12 BPB and buffers.
 # Conservative: signal unknown medium change on B: every check so DOS cannot reuse stale floppy directory sectors.
 target='''(uint16_t)(boot->request_offset + MD_REQ_MEDIA_RESULT), 1u);'''
 d=replace1(d,target,'''(uint16_t)(boot->request_offset + MD_REQ_MEDIA_RESULT), unit == 1u ? 0xFFu : 1u);''','B media change')
 # Source staged atomically after all matches validated.
 boot.write_text(sb,encoding='utf-8');driver.write_text(d,encoding='utf-8')
 print('Installed live B: floppy selection. Rebuild. DISK.COM must be copied into DOS A: once.')
 print('Images are read only; existing A:/C: write handling and flashing unchanged.')

if __name__=='__main__':main()
