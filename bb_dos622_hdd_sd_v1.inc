/* BB_DOS622_HDD_V1 -- isolated MS-DOS 6.22 HDD image (real MBR/FAT16).
 * Included after bb_dos622_sd.inc; uses its existing SPI1 retiming.
 * This never opens, changes or aliases the DOS2 DRIVE_C.IMG superfloppy.
 */
#ifndef BB_DOS622_HDD_SD_V1
#define BB_DOS622_HDD_SD_V1
#define BB622_HD_SECTORS 65520u
#define BB622_HD_BYTES ((FSIZE_t)BB622_HD_SECTORS * 512u)
static FIL bb622_hd_fil;
static bool bb622_hd_open;
static uint32_t bb622_hd_read_n, bb622_hd_write_n, bb622_hd_error_n;

bool bb_sd_hdd_available(void) { return bb622_hd_open; }

static void bb622_hd_mount(const char *drive)
{
    char path[96];
    UINT got=0;
    FRESULT fr;
    uint8_t mbr[512],bpb[512];
    bb622_hd_open=false;
    if (!bb_sd_dos622_active()) return;
    if (snprintf(path,sizeof(path),"%s/BLITZBUS/DOS622_HDD.IMG",drive) >= (int)sizeof(path)) return;
    fr=f_open(&bb622_hd_fil,path,FA_READ|FA_WRITE);
    if(fr!=FR_OK){printf("[bb622-hdd] optional image not opened fr=%d (DOS622 setup floppy only)\n",(int)fr);return;}
    if(f_size(&bb622_hd_fil)!=BB622_HD_BYTES){
        printf("[bb622-hdd] rejected: size=%lu expected=%lu\n",(unsigned long)f_size(&bb622_hd_fil),(unsigned long)BB622_HD_BYTES);
        (void)f_close(&bb622_hd_fil);return;
    }
    fr=f_read(&bb622_hd_fil,mbr,512u,&got);
    if(fr!=FR_OK||got!=512u||mbr[510]!=0x55u||mbr[511]!=0xAAu||
       mbr[446]!=0x80u||mbr[450]!=0x06u||
       mbr[454]!=63u||mbr[455]!=0u||mbr[456]!=0u||mbr[457]!=0u||
       mbr[458]!=0xB1u||mbr[459]!=0xFFu||mbr[460]!=0u||mbr[461]!=0u){
        printf("[bb622-hdd] rejected: MBR partition mismatch\n");
        (void)f_close(&bb622_hd_fil);return;
    }
    got=0;
    fr=f_lseek(&bb622_hd_fil,(FSIZE_t)63u*512u);
    if(fr==FR_OK)fr=f_read(&bb622_hd_fil,bpb,512u,&got);
    if(fr!=FR_OK||got!=512u||bpb[510]!=0x55u||bpb[511]!=0xAAu||
       bpb[11]!=0u||bpb[12]!=2u||bpb[13]!=4u||bpb[16]!=2u||
       bpb[28]!=63u||bpb[29]!=0u||bpb[30]!=0u||bpb[31]!=0u){
        printf("[bb622-hdd] rejected: FAT16 BPB mismatch\n");
        (void)f_close(&bb622_hd_fil);return;
    }
    bb622_hd_read_n=bb622_hd_write_n=bb622_hd_error_n=0;
    bb622_hd_open=true;
    printf("[bb622-hdd] BIOS 80h mounted RW 65x16x63, %lu sectors, partition LBA 63, FAT16\n",(unsigned long)BB622_HD_SECTORS);
}

bool bb_sd_hdd_read_sector(uint32_t lba,uint8_t *buf,size_t size)
{
    UINT got=0;
    FRESULT fr;
    if(!bb622_hd_open||!buf||size!=512u||lba>=BB622_HD_SECTORS)return false;
    bb622_retime_spi1();
    fr=f_lseek(&bb622_hd_fil,(FSIZE_t)lba*512u);
    if(fr==FR_OK)fr=f_read(&bb622_hd_fil,buf,512u,&got);
    if(fr!=FR_OK||got!=512u){
        if(++bb622_hd_error_n<=8u)printf("[bb622-hdd] READ FAIL lba=%lu fr=%d bytes=%u\n",(unsigned long)lba,(int)fr,(unsigned)got);
        return false;
    }
    if(++bb622_hd_read_n<=8u)printf("[bb622-hdd] read LBA=%lu OK\n",(unsigned long)lba);
    return true;
}

bool bb_sd_hdd_write_sector(uint32_t lba,const uint8_t *buf,size_t size)
{
    UINT put=0;
    FRESULT fr;
    if(!bb622_hd_open||!buf||size!=512u||lba>=BB622_HD_SECTORS)return false;
    bb622_retime_spi1();
    fr=f_lseek(&bb622_hd_fil,(FSIZE_t)lba*512u);
    if(fr==FR_OK)fr=f_write(&bb622_hd_fil,buf,512u,&put);
    if(fr==FR_OK&&put==512u)fr=f_sync(&bb622_hd_fil);
    if(fr!=FR_OK||put!=512u){
        if(++bb622_hd_error_n<=8u)printf("[bb622-hdd] WRITE FAIL lba=%lu fr=%d bytes=%u\n",(unsigned long)lba,(int)fr,(unsigned)put);
        return false;
    }
    if(++bb622_hd_write_n<=8u)printf("[bb622-hdd] write LBA=%lu SYNC OK\n",(unsigned long)lba);
    return true;
}
#endif
