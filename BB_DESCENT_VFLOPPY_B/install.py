from pathlib import Path
import argparse, shutil, datetime

def one(s,a,b,tag):
 n=s.count(a)
 if n!=1: raise RuntimeError(f'{tag}: expected 1 match, found {n}. No files modified.')
 return s.replace(a,b,1)

def main():
 p=argparse.ArgumentParser(description='Install separate read-only DOS B: virtual Descent floppy')
 p.add_argument('--root',default=r'C:\blitzBUS');p.add_argument('--restore',action='store_true');a=p.parse_args()
 root=Path(a.root);boot=root/'sd_boot'/'bb_sd_boot.c';drv=root/'sd_boot'/'bb_msdos2_boot.c'
 backup=root/'sd_boot'/'stage2e_b_floppy_backup'; files=(boot,drv)
 if a.restore:
  for f in files:
   src=backup/f.name
   if not src.is_file(): raise RuntimeError('Missing backup '+str(src))
  for f in files: shutil.copy2(backup/f.name,f)
  print('B: virtual floppy changes restored; rebuild.');return
 if not all(f.is_file() for f in files):raise RuntimeError('Missing Stage2D files: '+str(files))
 sb=boot.read_text(encoding='utf-8');sd=drv.read_text(encoding='utf-8')
 if 'BB_DESCENT_VFLOPPY_B_V1' in sb:raise RuntimeError('Already installed; refusing duplicate change')
 if 'BB_STAGE2D_C_READ_CACHE' not in sb or 'BB_STAGE2C_C_WRITABLE' not in sd:raise RuntimeError('Expected working Stage2D/Stage2C baseline missing')
 sb=one(sb,'static FIL bb_c_img;', 'static FIL bb_b_img;\nstatic bool bb_b_open;\nstatic unsigned bb_b_number;\nstatic FIL bb_c_img;', 'B globals')
 sb=one(sb,'    bb_c_open = false;\n    bb_c_cache_reset();','    bb_b_open = false;\n    bb_b_number = 0u;\n    bb_c_open = false;\n    bb_c_cache_reset();','B init')
 # Shared card must be mounted and boot image loaded before opening B.
 hook='    bb_img_open = true;\n'
 inject=r'''    /* Boot-time B: selection, read-only. The selector is one ASCII digit 1..5. */
    {
        FIL sel;
        char selector[96];
        char bpath[96];
        char choice = '1';
        UINT nread = 0u;
        if (snprintf(selector, sizeof(selector), "%s/BLITZBUS/B_DISK.TXT", drive) < (int)sizeof(selector)) {
            if (f_open(&sel, selector, FA_READ) == FR_OK) {
                if (f_read(&sel, &choice, 1u, &nread) != FR_OK || nread != 1u)
                    choice = '1';
                (void)f_close(&sel);
            }
        }
        if (choice < '1' || choice > '5') {
            printf("[bb-sd-b] invalid B_DISK.TXT selection=%d, using disk1\n", (int)(unsigned char)choice);
            choice = '1';
        }
        bb_b_number = (unsigned)(choice - '0');
        if (snprintf(bpath, sizeof(bpath), "%s/BLITZBUS/DESCENT%c.IMG", drive, choice) < (int)sizeof(bpath)) {
            FRESULT bf = f_open(&bb_b_img, bpath, FA_READ);
            if (bf == FR_OK) {
                if (f_size(&bb_b_img) == (FSIZE_t)1474560u) {
                    bb_b_open = true;
                    printf("[bb-sd-b] B: DESCENT%c.IMG READ-ONLY 1440 KiB mounted\n", choice);
                } else {
                    printf("[bb-sd-b] B: wrong image size=%lu\n", (unsigned long)f_size(&bb_b_img));
                    (void)f_close(&bb_b_img);
                }
            } else {
                printf("[bb-sd-b] B: open result=%d (A/C remain functional)\n", (int)bf);
            }
        }
    }
'''
 sb=one(sb,hook,inject+hook,'B mount')
 sb+=r'''
/* BB_DESCENT_VFLOPPY_B_V1
 * Read-only 1.44 MiB FAT12 floppy image for DOS unit 1 (B:).
 * Selection: /BLITZBUS/B_DISK.TXT one digit 1..5; reboot to change.
 * Reads are NOT cached, and disk images are NEVER modified.
 */
bool bb_sd_b_available(void) { return bb_b_open; }
bool bb_sd_b_read_sector(uint32_t sector, uint8_t *data, size_t size)
{
    FRESULT fr;
    UINT got=0u;
    static unsigned long reads;
    if (!bb_b_open || !data || size != 512u || sector >= 2880u) return false;
    (void)spi_set_baudrate(spi1, 12500000u);
    fr = f_lseek(&bb_b_img, (FSIZE_t)sector * 512u);
    if (fr == FR_OK) fr=f_read(&bb_b_img, data, 512u, &got);
    if (fr != FR_OK || got != 512u) {
        printf("[bb-sd-b] READ ERROR disk=%u lba=%lu fr=%d got=%u\n",
               bb_b_number, (unsigned long)sector, (int)fr, (unsigned)got);
        return false;
    }
    if (++reads <= 6u)
        printf("[bb-sd-b] read disk=%u lba=%lu OK\n",bb_b_number,(unsigned long)sector);
    return true;
}
'''
 sd=one(sd,'extern bool bb_sd_c_available(void);', 'extern bool bb_sd_b_available(void);\nextern bool bb_sd_b_read_sector(uint32_t, uint8_t *, size_t);\nextern bool bb_sd_c_available(void);','B declaration')
 sd=one(sd,'md_x86_write16(cpu, seg, MD_MSDOS2_BPB_TABLE_OFFSET + 2u, MD_MSDOS2_BPB_OFFSET);','md_x86_write16(cpu, seg, MD_MSDOS2_BPB_TABLE_OFFSET + 2u, 0x0360u);','B BPB table')
 marker='    /* C: BPB values are read directly from the generated 16 MiB FAT16 image. */'
 bp=r'''    /* B: standard 1.44 MiB 3.5-inch FAT12 BPB. */
    md_x86_write16(cpu, seg, 0x0360u + 0u, 512u);
    md_x86_write8(cpu, seg, 0x0360u + 2u, 1u);
    md_x86_write16(cpu, seg, 0x0360u + 3u, 1u);
    md_x86_write8(cpu, seg, 0x0360u + 5u, 2u);
    md_x86_write16(cpu, seg, 0x0360u + 6u, 224u);
    md_x86_write16(cpu, seg, 0x0360u + 8u, 2880u);
    md_x86_write8(cpu, seg, 0x0360u + 10u, 0xF0u);
    md_x86_write16(cpu, seg, 0x0360u + 11u, 9u);
'''
 sd=one(sd,marker,bp+marker,'B BPB')
 guard='unit > 2u || (unit == 2u && !bb_sd_c_available())'
 if sd.count(guard)!=3:raise RuntimeError(f'unit guard occurrences expected 3 got {sd.count(guard)}')
 sd=sd.replace(guard,'unit > 2u || (unit == 1u && !bb_sd_b_available()) || (unit == 2u && !bb_sd_c_available())')
 sd=one(sd,'(unit == 2u ? 32768u : boot->disk.sector_count)', '(unit == 2u ? 32768u : (unit == 1u ? 2880u : boot->disk.sector_count))','B size')
 # Write guard must short-circuit B even when A writable; never call A write on B.
 write_anchor='''        if (write) {
            if (unit != 2u && !boot->disk.writable'''
 # Stage2C has conditional guard variations. Insert guard independent of them.
 start=sd.find('static bool MD_DOS_HOT_FUNC(md_disk_transfer)')
 pos=sd.find('        if (write) {', start)
 if pos<0:raise RuntimeError('cannot locate transfer write branch')
 sd=sd[:pos]+sd[pos:].replace('        if (write) {','''        if (write) {
            if (unit == 1u) {
                md_device_error(runtime, boot, MD_DEV_ERR_WRITE_FAULT);
                return true;
            }''',1)
 original='''            if ((unit == 2u && !bb_sd_c_read_sector(lba, sector, sizeof(sector))) ||
                (unit != 2u && (boot->disk.read == NULL ||
                !boot->disk.read(boot->disk.user, lba, sector, boot->disk.sector_size)))) {'''
 replacement='''            if ((unit == 1u && !bb_sd_b_read_sector(lba, sector, sizeof(sector))) ||
                (unit == 2u && !bb_sd_c_read_sector(lba, sector, sizeof(sector))) ||
                (unit == 0u && (boot->disk.read == NULL ||
                !boot->disk.read(boot->disk.user, lba, sector, boot->disk.sector_size)))) {'''
 sd=one(sd,original,replacement,'B read dispatch')
 sd=one(sd,'unit == 2u ? 0xF8u : 0xFDu','unit == 2u ? 0xF8u : (unit == 1u ? 0xF0u : 0xFDu)','media')
 sd=one(sd,'unit == 2u ? 0x0340u : MD_MSDOS2_BPB_OFFSET','unit == 2u ? 0x0340u : (unit == 1u ? 0x0360u : MD_MSDOS2_BPB_OFFSET)','BPB service')
 # Make changes only after all validations.
 backup.mkdir(parents=True,exist_ok=True)
 for f in files:
  if not (backup/f.name).exists():shutil.copy2(f,backup/f.name)
 boot.write_text(sb,encoding='utf-8');drv.write_text(sd,encoding='utf-8')
 print('Installed read-only B: virtual floppy; A: and C: unchanged. Backups at:',backup)
 print('Select disk by changing B_DISK.TXT with Pico powered OFF, then reboot.')
if __name__=='__main__':main()
