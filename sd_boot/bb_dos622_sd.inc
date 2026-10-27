/* BB_DOS622_IPL_V1 - optional separate MS-DOS 6.x boot floppy from SD.
   This code intentionally never modifies the established BOOT.IMG path. */
static FIL bb622_disk;
static FIL bb622_swap_alt;
static FIL *bb622_swap_active=&bb622_disk;
static unsigned bb622_swap_a_number=1u;
static bool bb622_swap_a_changed;
static bool bb622_swap_a_ejected;
static bool bb622_disk_open;
static uint32_t bb622_read_calls;
static uint32_t bb622_read_errors;
/* BB_DOS622_CLOCKFIX_V1: SD SPI1 was configured with 48 MHz clk_peri
   before LCD init.  LCD raises clk_peri to 150 MHz; the old divider
   then makes SD traffic too fast and FatFs reports FR_DISK_ERR.
   B:/C: already retime SPI1 before their post-LCD accesses. */
static uint32_t bb622_retime_count;

/* BB_DOS622_PERF_V1: 12.5 MHz (25 MHz gave FR_DISK_ERR reads on the
   test card). -DBB622_SD_SPI_HZ=... to try another rate. Only retime when
   the rate is wrong. */
#ifndef BB622_SD_SPI_HZ
#define BB622_SD_SPI_HZ 12500000u
#endif
static void bb622_retime_spi1(void)
{
    const uint32_t old_baud = spi_get_baudrate(spi1);
    if (old_baud == BB622_SD_SPI_HZ && bb622_retime_count) return;
    const uint32_t new_baud = spi_set_baudrate(spi1, BB622_SD_SPI_HZ);
    if (++bb622_retime_count <= 2u) {
        printf("[bb-dos622-clockfix] spi1 old=%lu new=%lu peri=%lu\n",
               (unsigned long)old_baud, (unsigned long)new_baud,
               (unsigned long)clock_get_hz(clk_peri));
    }
}


bool bb_sd_dos622_active(void) { return bb622_disk_open; }

bool bb_sd_dos622_read_sector(uint32_t lba, uint8_t *dst, size_t length)
{
    FRESULT rc;
    UINT got = 0;
    if (!bb622_disk_open || bb622_swap_a_ejected || !dst || length != 512u || lba >= 2880u) return false;
    /* Must be done BEFORE the first FatFs operation after LCD clock init.
       Retiming an unrelated SPI interface (SPI0 LCD) would be incorrect. */
    bb622_retime_spi1();
    rc = f_lseek(bb622_swap_active, (FSIZE_t)lba * 512u);
    if (rc != FR_OK) {
        ++bb622_read_errors;
        if (bb622_read_errors <= 8u)
            printf("[bb-dos622] disk READ ERROR stage=seek lba=%lu fr=%d spi1=%lu\n",
                   (unsigned long)lba, (int)rc, (unsigned long)spi_get_baudrate(spi1));
        return false;
    }
    rc = f_read(bb622_swap_active, dst, 512u, &got);
    if (rc != FR_OK || got != 512u) {
        ++bb622_read_errors;
        if (bb622_read_errors <= 8u)
            printf("[bb-dos622] disk READ ERROR stage=read lba=%lu fr=%d bytes=%u spi1=%lu\n",
                   (unsigned long)lba, (int)rc, (unsigned)got,
                   (unsigned long)spi_get_baudrate(spi1));
        return false;
    }
    ++bb622_read_calls;
    if (bb622_read_calls <= 8u) printf("[bb-dos622] read lba=%lu OK\n", (unsigned long)lba);
    return true;
}

/* BB_DOS622_SWAP_LCD_V2: floppy A media exchange, DOS622 only.
 * Open new FAT12 image BEFORE closing old; invalid/missing leaves old intact.
 * NOSYS on second disk is intentional: SETUP floppy 2+ has no IO.SYS.
 */
static bool bb622_swap_fat12_valid(const uint8_t *b)
{
    return b[510]==0x55u && b[511]==0xAAu &&
        (b[0]==0xEBu || b[0]==0xE9u) &&
        b[11]==0u && b[12]==2u && b[13]==1u &&
        b[14]==1u && b[15]==0u && b[16]==2u &&
        b[17]==224u && b[18]==0u &&
        b[19]==0x40u && b[20]==0x0Bu &&
        b[22]==9u && b[23]==0u &&
        b[24]==18u && b[25]==0u && b[26]==2u && b[27]==0u;
}
bool bb_sd_dos622_take_a_change(void)
{
    const bool result=bb622_swap_a_changed;
    bb622_swap_a_changed=false;
    return result;
}
bool bb_sd_dos622_select_a(unsigned n)
{
    FIL *candidate;
    FRESULT fr;
    UINT got=0;
    uint8_t bs[512];
    char path[96];
    if(!bb622_disk_open || n<1u || n>9u)return false;
    if(n==bb622_swap_a_number && !bb622_swap_a_ejected)return true;
    if(n==1u) {
        if(snprintf(path,sizeof path,"0:/BLITZBUS/DOS622.IMG") >= (int)sizeof path)return false;
    } else if(snprintf(path,sizeof path,"0:/BLITZBUS/DOS622%u.IMG",n) >= (int)sizeof path)return false;
    bb622_retime_spi1();
    candidate = (bb622_swap_active==&bb622_disk) ? &bb622_swap_alt : &bb622_disk;
    fr=f_open(candidate,path,FA_READ);
    if(fr!=FR_OK) {
        printf("[bb622-swap] A:%u FAIL open fr=%d (previous disk retained)\n",n,(int)fr);
        return false;
    }
    if(f_size(candidate)!=1474560u ||
       f_read(candidate,bs,512u,&got)!=FR_OK || got!=512u ||
       !bb622_swap_fat12_valid(bs)) {
        printf("[bb622-swap] A:%u FAIL image must be 1440 KiB FAT12 (previous disk retained)\n",n);
        (void)f_close(candidate);
        return false;
    }
    (void)f_close(bb622_swap_active);
    bb622_swap_active=candidate;
    bb622_swap_a_number=n;
    bb622_swap_a_ejected=false;
    bb622_swap_a_changed=true;
    printf("[bb622-swap] A:%u OK read-only; BIOS media changed\n",n);
    fflush(stdout);
    return true;
}

/* BB_DOS622_BOOT_EJECT_V1: eject A without ending the DOS6 session.
 * The running OS owns DOS6, but a floppy may temporarily have no media.
 */
bool bb_sd_dos622_a_image_ready(void) { return bb622_disk_open && !bb622_swap_a_ejected; }
bool bb_sd_dos622_eject_a(void)
{
    if(!bb622_disk_open) return false;
    if(!bb622_swap_a_ejected) {
        bb622_retime_spi1();
        (void)f_close(bb622_swap_active);
        bb622_swap_a_ejected=true;
    }
    bb622_swap_a_changed=true;
    printf("[bb622-swap] A:0 OK ejected; BIOS media changed\n");fflush(stdout);
    return true;
}

/* BB_DOS622_BOOT_EJECT_V1: explicit cold-boot selector on the microSD.
 * The legacy DOS2 path and default DOS6 A: boot are unchanged.
 * C requires BOOT_DRIVE.TXT containing the single ASCII letter C.
 */
extern bool bb_sd_hdd_available(void);
static char bb622_boot_drive='A';
static void bb622_pick_boot(const char *drive)
{
    FIL f;FRESULT rc;UINT got=0;char choice='A';char path[96];
    bb622_boot_drive='A';
    if(!bb_sd_dos622_active())return;
    if(snprintf(path,sizeof path,"%s/BLITZBUS/BOOT_DRIVE.TXT",drive)>=(int)sizeof path)return;
    rc=f_open(&f,path,FA_READ);
    if(rc==FR_OK){
        rc=f_read(&f,&choice,1u,&got);
        (void)f_close(&f);
        if(rc==FR_OK && got==1u && (choice=='C'||choice=='c'))bb622_boot_drive='C';
        else if(choice!='A' && choice!='a')printf("[bb622-boot] invalid BOOT_DRIVE.TXT, using A\n");
    }
    if(bb622_boot_drive=='C' && !bb_sd_hdd_available()) {
        printf("[bb622-boot] C requested but HDD absent; fallback A\n");
        bb622_boot_drive='A';
    }
    printf("[bb622-boot] cold boot selector=%c (A=setup, C=installed HDD)\n",bb622_boot_drive);
}
bool bb_sd_dos622_boot_c(void) {return bb622_boot_drive=='C';}

/* DOS 6.x floppy boot candidates need the ordinary 1.44MB FAT12 layout.
   Presence of three system filenames does not certify a version/license.
   Full boot-sector execution, not this check, determines bootability. */
static void bb622_mount(const char *drive)
{
    FIL select;
    char selname[96], imgname[96];
    uint8_t sector[512];
    char flag = 0;
    UINT got = 0;
    bool have_io = false, have_dos = false, have_cmd = false;
    uint32_t root, nroot, lba;
    FRESULT rc;
    bb622_disk_open = false;
    bb622_swap_active=&bb622_disk;bb622_swap_a_number=1u;bb622_swap_a_changed=false;bb622_swap_a_ejected=false;
    bb622_read_calls = bb622_read_errors = 0;
    if (snprintf(selname, sizeof selname, "%s/BLITZBUS/DOS622.TXT", drive) >= (int)sizeof selname) return;
    if (f_open(&select, selname, FA_READ) != FR_OK) return; /* opt-in only */
    rc = f_read(&select, &flag, 1u, &got);
    (void)f_close(&select);
    if (rc != FR_OK || got != 1u || flag != '1') {
        printf("[bb-dos622] DOS622.TXT found but disabled (write 1 to enable)\n");
        return;
    }
    if (snprintf(imgname, sizeof imgname, "%s/BLITZBUS/DOS622.IMG", drive) >= (int)sizeof imgname) return;
    rc = f_open(&bb622_disk, imgname, FA_READ);  /* read-only by design */
    if (rc != FR_OK) { printf("[bb-dos622] ERROR opening DOS622.IMG: %d\n", (int)rc); return; }
    if (f_size(&bb622_disk) != (FSIZE_t)1474560u ||
        f_read(&bb622_disk, sector, 512u, &got) != FR_OK || got != 512u) {
        printf("[bb-dos622] ERROR image must be exactly 1,474,560 bytes\n");
        (void)f_close(&bb622_disk); return;
    }
    if (sector[510] != 0x55u || sector[511] != 0xAAu ||
        (sector[0] != 0xEBu && sector[0] != 0xE9u) ||
        sector[11] != 0x00u || sector[12] != 0x02u || /* 512 bytes/sector */
        sector[13] != 1u || sector[14] != 1u || sector[15] != 0u ||
        sector[16] != 2u || sector[17] != 224u || sector[18] != 0u ||
        sector[19] != 0x40u || sector[20] != 0x0Bu ||
        sector[22] != 9u || sector[23] != 0u ||
        sector[24] != 18u || sector[25] != 0u ||
        sector[26] != 2u || sector[27] != 0u) {
        printf("[bb-dos622] ERROR invalid 1.44MB FAT12 boot BPB/signature\n");
        (void)f_close(&bb622_disk); return;
    }
    root = 1u + 2u * 9u;
    nroot = 14u;
    for (lba = root; lba < root + nroot; ++lba) {
        unsigned k;
        if (f_lseek(&bb622_disk, (FSIZE_t)lba * 512u) != FR_OK ||
            f_read(&bb622_disk, sector, 512u, &got) != FR_OK || got != 512u) break;
        for (k = 0; k < 512u; k += 32u) {
            const uint8_t *e = sector + k;
            if (e[0] == 0x00u) goto finished_root;
            if (e[0] == 0xE5u || (e[11] & 0x18u) != 0u) continue;
            if (memcmp(e, "IO      SYS", 11u) == 0) have_io = true;
            if (memcmp(e, "MSDOS   SYS", 11u) == 0) have_dos = true;
            if (memcmp(e, "COMMAND COM", 11u) == 0) have_cmd = true;
        }
    }
finished_root:
    if (!have_io || !have_dos || !have_cmd) {
        printf("[bb-dos622] ERROR missing IO.SYS=%u MSDOS.SYS=%u COMMAND.COM=%u\n",
               (unsigned)have_io, (unsigned)have_dos, (unsigned)have_cmd);
        (void)f_close(&bb622_disk); return;
    }
    bb622_disk_open = true;
    printf("[bb-dos622] DOS622.IMG boot candidate mounted A: 1440KiB READ-ONLY (opt-in)\n");
}
