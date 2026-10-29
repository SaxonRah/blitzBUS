/* BB_DOS622_HDD_V1 -- isolated MS-DOS 6.22 HDD image (real MBR/FAT16).
 * Included after bb_dos622_sd.inc; uses its existing SPI1 retiming.
 * This never opens, changes or aliases the DOS2 DRIVE_C.IMG superfloppy.
 */
#ifndef BB_DOS622_HDD_SD_V1
#define BB_DOS622_HDD_SD_V1
#define BB622_HD_SECTORS 258048u
#define BB622_HD_BYTES ((FSIZE_t)BB622_HD_SECTORS * 512u)
static FIL bb622_hd_fil;
static bool bb622_hd_open;
static uint32_t bb622_hd_read_n, bb622_hd_write_n, bb622_hd_error_n;
/* BB_DOS622_PERF_V1: FatFs fast seek (cluster link map) - without it every
   backward f_lseek in the 126 MB image walks the FAT chain from the start.
   Writes are full aligned sectors (FatFs writes them straight to the card);
   f_sync only every BB622_SYNC_EVERY writes instead of after each one. */
#ifndef BB622_SYNC_EVERY
#define BB622_SYNC_EVERY 64u
#endif
#if FF_USE_FASTSEEK
static DWORD bb622_hd_clmt[256];
#endif
static uint32_t bb622_hd_unsynced;

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
       mbr[458]!=0xC1u||mbr[459]!=0xEFu||mbr[460]!=0x03u||mbr[461]!=0u){
        printf("[bb622-hdd] rejected: MBR partition mismatch\n");
        (void)f_close(&bb622_hd_fil);return;
    }
    got=0;
    fr=f_lseek(&bb622_hd_fil,(FSIZE_t)63u*512u);
    if(fr==FR_OK)fr=f_read(&bb622_hd_fil,bpb,512u,&got);
    if(fr!=FR_OK||got!=512u||bpb[510]!=0x55u||bpb[511]!=0xAAu||
       bpb[11]!=0u||bpb[12]!=2u||bpb[13]!=4u||bpb[16]!=2u||
       bpb[19]!=0u||bpb[20]!=0u||bpb[22]!=0xFCu||bpb[23]!=0u||
       bpb[32]!=0xC1u||bpb[33]!=0xEFu||bpb[34]!=0x03u||bpb[35]!=0u||
       bpb[28]!=63u||bpb[29]!=0u||bpb[30]!=0u||bpb[31]!=0u){
        printf("[bb622-hdd] rejected: FAT16 BPB mismatch\n");
        (void)f_close(&bb622_hd_fil);return;
    }
    bb622_hd_read_n=bb622_hd_write_n=bb622_hd_error_n=0;
#if FF_USE_FASTSEEK
    bb622_hd_clmt[0]=sizeof bb622_hd_clmt/sizeof bb622_hd_clmt[0];
    bb622_hd_fil.cltbl=bb622_hd_clmt;
    fr=f_lseek(&bb622_hd_fil,CREATE_LINKMAP);
    if(fr!=FR_OK){bb622_hd_fil.cltbl=0;printf("[bb622-hdd] fast seek off (fr=%d, %lu fragments)\n",(int)fr,(unsigned long)bb622_hd_clmt[0]);}
    else printf("[bb622-hdd] fast seek ON (%lu link-map words)\n",(unsigned long)bb622_hd_clmt[0]);
#else
    printf("[bb622-hdd] fast seek not compiled (FF_USE_FASTSEEK=0)\n");
#endif
    bb622_hd_unsynced=0;
    bb622_hd_open=true;
    printf("[bb622-hdd] BIOS 80h mounted RW 256x16x63, %lu sectors, partition LBA 63, FAT16\n",(unsigned long)BB622_HD_SECTORS);
}

/* BB622_HDD_LIFE_V2: additive observer only. No reopen/retry/remount. */
static FATFS *bb_life_v2_initial_fs;
static WORD bb_life_v2_initial_id;
static uint32_t bb_life_v2_ops, bb_life_v2_errors;
static uint32_t bb_life_v2_lba;
static unsigned bb_life_v2_mode;
static bool bb_life_v2_seen, bb_life_v2_warned;

static void bb_life_v2_dump(const char *stage, FRESULT result, UINT transferred)
{
    sd_card_t *card=sd_get_by_num(0u);
    FATFS *active=card ? &card->state.fatfs : NULL;
    FATFS *handle=bb622_hd_fil.obj.fs; /* opaque: NEVER dereference */
    printf("[bb622-hdd-life] %s lba=%lu fr=%d bytes=%u ops=%lu faults=%lu "
           "fil=%p fil.fs=%p active.fs=%p initial.fs=%p "
           "fil.id=%u active.id=%u initial.id=%u fs_type=%u mounted=%u "
           "eq-active=%u eq-initial=%u status=%u\n",
           stage,(unsigned long)bb_life_v2_lba,(int)result,(unsigned)transferred,
           (unsigned long)bb_life_v2_ops,(unsigned long)bb_life_v2_errors,
           (void*)&bb622_hd_fil,(void*)handle,(void*)active,(void*)bb_life_v2_initial_fs,
           (unsigned)bb622_hd_fil.obj.id,(unsigned)(active?active->id:0u),
           (unsigned)bb_life_v2_initial_id,(unsigned)(active?active->fs_type:0u),
           (unsigned)(card?card->state.mounted:0u),
           (unsigned)(handle==active),(unsigned)(handle==bb_life_v2_initial_fs),
           (unsigned)disk_status(0u));
}
static void bb_life_v2_fault(const char *stage, FRESULT fr, UINT transferred)
{
    ++bb_life_v2_errors;
    if(bb_life_v2_errors<=12u)bb_life_v2_dump(stage,fr,transferred);
}
static void bb_life_v2_enter(unsigned mode, uint32_t lba)
{
    sd_card_t *card=sd_get_by_num(0u);
    FATFS *active=card ? &card->state.fatfs : NULL;
    bb_life_v2_mode=mode;bb_life_v2_lba=lba;
    ++bb_life_v2_ops;
    if(!bb_life_v2_seen){
        bb_life_v2_initial_fs=active;
        bb_life_v2_initial_id=active?active->id:0u;
        bb_life_v2_seen=true;
        bb_life_v2_dump("first-io",FR_OK,0u);
    }
    if(!(bb_life_v2_ops&4095u) && !bb_life_v2_warned){
        if(!active || active!=bb_life_v2_initial_fs ||
           bb622_hd_fil.obj.fs!=active ||
           bb622_hd_fil.obj.id!=active->id ||
           active->id!=bb_life_v2_initial_id ||
           !active->fs_type || !card->state.mounted){
            bb_life_v2_warned=true;
            bb_life_v2_dump("early-id-mismatch",FR_INVALID_OBJECT,0u);
        }
    }
}
static FRESULT bb_life_v2_seek(FIL *f, FSIZE_t off)
{
    FRESULT fr=f_lseek(f,off);
    if(fr!=FR_OK)bb_life_v2_fault(bb_life_v2_mode==1u?"seek-read":"seek-write",fr,0u);
    return fr;
}
static FRESULT bb_life_v2_read(FIL *f, void *buf, UINT n, UINT *got)
{
    FRESULT fr=f_read(f,buf,n,got);
    if(fr!=FR_OK || !got || *got!=n)bb_life_v2_fault("read",fr,got?*got:0u);
    return fr;
}
static FRESULT bb_life_v2_write(FIL *f, const void *buf, UINT n, UINT *put)
{
    FRESULT fr=f_write(f,buf,n,put);
    if(fr!=FR_OK || !put || *put!=n)bb_life_v2_fault("write",fr,put?*put:0u);
    return fr;
}
static FRESULT bb_life_v2_sync(FIL *f)
{
    FRESULT fr=f_sync(f);
    if(fr!=FR_OK)bb_life_v2_fault(bb_life_v2_mode==3u?"sync-flush":"sync-write",fr,0u);
    return fr;
}
/* END BB622_HDD_LIFE_V2 HELPER */

bool bb_sd_hdd_read_sector(uint32_t lba,uint8_t *buf,size_t size)
{
#define f_lseek bb_life_v2_seek
#define f_read bb_life_v2_read
    bb_life_v2_enter(1u, lba);

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

#undef f_lseek
#undef f_read
}

bool bb_sd_hdd_write_sector(uint32_t lba,const uint8_t *buf,size_t size)
{
#define f_lseek bb_life_v2_seek
#define f_write bb_life_v2_write
#define f_sync bb_life_v2_sync
    bb_life_v2_enter(2u, lba);

    UINT put=0;
    FRESULT fr;
    if(!bb622_hd_open||!buf||size!=512u||lba>=BB622_HD_SECTORS)return false;
    bb622_retime_spi1();
    fr=f_lseek(&bb622_hd_fil,(FSIZE_t)lba*512u);
    if(fr==FR_OK)fr=f_write(&bb622_hd_fil,buf,512u,&put);
    if(fr==FR_OK&&put==512u&&++bb622_hd_unsynced>=BB622_SYNC_EVERY){fr=f_sync(&bb622_hd_fil);bb622_hd_unsynced=0;}
    if(fr!=FR_OK||put!=512u){
        if(++bb622_hd_error_n<=8u)printf("[bb622-hdd] WRITE FAIL lba=%lu fr=%d bytes=%u\n",(unsigned long)lba,(int)fr,(unsigned)put);
        return false;
    }
    if(++bb622_hd_write_n<=8u)printf("[bb622-hdd] write LBA=%lu OK\n",(unsigned long)lba);
    return true;

#undef f_lseek
#undef f_write
#undef f_sync
}

/* BB_DOS622_PERF_V1: flush pending HDD writes (call when idle / on exit) */
void bb_sd_hdd_flush(void)
{
#define f_sync bb_life_v2_sync
    bb_life_v2_enter(3u, 0u);

    if(bb622_hd_open&&bb622_hd_unsynced){bb622_retime_spi1();(void)f_sync(&bb622_hd_fil);bb622_hd_unsynced=0;}

#undef f_sync
}
#endif
