/* blitzBUS Stage 2A: SD-backed FAT12 image with persistent sector writes.
 * SD is initialized before LCD clock setup. Retains BOOT.IMG open for writes.
 * The loaded disk lives in PSRAM, but SD writes are synchronous and checked.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ff.h"
#include "diskio.h"
#include "hw_config.h"
#include "sd_card.h"
#include "hardware/clocks.h"
#include "hardware/spi.h"

#define BB_SD_BYTES 368640u
#define BB_SD_SECTOR 512u
static FIL bb_b_img;
static bool bb_b_open;
static unsigned bb_b_number;
static FIL bb_c_img;
static bool bb_c_open;
static void bb_c_cache_reset(void);
static FIL bb_img;
static bool bb_img_open;
static unsigned long bb_write_count;
static unsigned long bb_write_errors;

bool bb_sd_boot_image(uint8_t *dest, unsigned bytes)
{
    sd_card_t *sd;
    const char *drive;
    char path[96];
    FRESULT err;
    UINT got;
    unsigned offset;

    bb_b_open = false;
    bb_b_number = 0u;
    bb_c_open = false;
    bb_c_cache_reset();
    bb_img_open = false;
    bb_write_count = bb_write_errors = 0;
    if (!dest || bytes != BB_SD_BYTES) return false;
    if (!sd_init_driver()) { printf("[bb-sd] driver init failed; fallback\n"); return false; }
    sd = sd_get_by_num(0u);
    if (!sd) { printf("[bb-sd] missing card definition; fallback\n"); return false; }
    drive = sd_get_drive_prefix(sd);
    if (!drive) return false;
    printf("[bb-sd-prelcd] status=0x%02x card-type=%d\n",
           (unsigned)disk_status(0u), (int)sd->state.card_type);
    err = f_mount(&sd->state.fatfs, drive, 1u);
    if (err != FR_OK) { printf("[bb-sd] mount=%d fallback\n", (int)err); return false; }
    sd->state.mounted = true;
    if (snprintf(path, sizeof(path), "%s/BLITZBUS/BOOT.IMG", drive) >= (int)sizeof(path)) return false;
    err = f_open(&bb_img, path, FA_READ | FA_WRITE);
    if (err != FR_OK) {
        printf("[bb-sd] open RW=%d (image must be writable); fallback\n", (int)err);
        return false;
    }
    if (f_size(&bb_img) != BB_SD_BYTES) {
        printf("[bb-sd] bad image size=%lu; fallback\n", (unsigned long)f_size(&bb_img));
        (void)f_close(&bb_img);
        return false;
    }
    offset = 0;
    while (offset < bytes) {
        const UINT want = bytes - offset > 4096u ? 4096u : (UINT)(bytes - offset);
        got = 0;
        err = f_read(&bb_img, dest + offset, want, &got);
        if (err != FR_OK || got != want) {
            printf("[bb-sd] load offset=%u result=%d bytes=%u; fallback\n", offset, (int)err, got);
            (void)f_close(&bb_img);
            return false;
        }
        offset += got;
    }
    /* Stage 2B C: opens only after known-good A:, before LCD clock change. */
    {
        char cpath[96];
        if (snprintf(cpath, sizeof(cpath), "%s/BLITZBUS/DRIVE_C.IMG", drive) < (int)sizeof(cpath)) {
            FRESULT cf = f_open(&bb_c_img, cpath, FA_READ | FA_WRITE);
            if (cf == FR_OK) {
                if (f_size(&bb_c_img) == (FSIZE_t)(16777216u)) {
                    bb_c_open = true;
                    printf("[bb-sd-c] DRIVE_C.IMG opened READ-WRITE 16 MiB\n");
                } else {
                    printf("[bb-sd-c] wrong image size=%lu expected=16777216\n",
                           (unsigned long)f_size(&bb_c_img));
                    (void)f_close(&bb_c_img);
                }
            } else {
                printf("[bb-sd-c] C: unavailable open=%d (A: remains working)\n", (int)cf);
            }
        }
    }
    /* Boot-time B: selection, read-only. The selector is one ASCII digit 1..5. */
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
    bb_img_open = true;
    printf("[bb-sd] A: BOOT.IMG %u bytes loaded; PERSISTENT WRITE-THROUGH ACTIVE\n", bytes);
    return true;
}

/* On-demand, read-only runtime probe after the LCD changes clk_peri. */
static void bb_sd_io_diag(const char *stage, uint32_t sector,
                          FRESULT result, unsigned wrote)
{
    const DSTATUS ds = disk_status(0u);
    printf("[bb-sd-io] stage=%s lba=%lu fr=%d wrote=%u "
           "status=0x%02x peri=%lu spi1-baud=%lu errors=%lu\n",
           stage, (unsigned long)sector, (int)result, wrote,
           (unsigned)ds, (unsigned long)clock_get_hz(clk_peri),
           (unsigned long)spi_get_baudrate(spi1), bb_write_errors);
}

bool bb_sd_persist_sector(uint32_t sector, const uint8_t *data, size_t size)
{
    FRESULT err;
    UINT written = 0u;
    const FSIZE_t off = (FSIZE_t)sector * BB_SD_SECTOR;
    if (!bb_img_open) return true; /* Embedded fallback remains volatile. */
    if (!data || size != BB_SD_SECTOR || sector >= BB_SD_BYTES / BB_SD_SECTOR)
        return false;
    /* LCD initialization raises clk_peri from 48 to 150 MHz. The SPI1
     * divisor that once yielded 12 MHz then yields 37.5 MHz, even though
     * the SD driver's configured target is only 12.5 MHz. Reprogram the
     * hardware SPI1 divider before any post-LCD SD transaction.
     * Reapplying it before each write also protects against future clock
     * changes. SPI0 (LCD) is not touched.
     */
    {
        const uint32_t old_baud = spi_get_baudrate(spi1);
        const uint32_t adjusted = spi_set_baudrate(spi1, 12500000u);
        if (bb_write_count == 0u && bb_write_errors == 0u)
            printf("[bb-sd-clockfix] spi1 old=%lu new=%lu peri=%lu\n",
                   (unsigned long)old_baud, (unsigned long)adjusted,
                   (unsigned long)clock_get_hz(clk_peri));
    }
    if (bb_write_count == 0u && bb_write_errors == 0u)
        bb_sd_io_diag("before-first-write", sector, FR_OK, 0u);

    err = f_lseek(&bb_img, off);
    if (err != FR_OK) {
        ++bb_write_errors;
        bb_sd_io_diag("seek-failed", sector, err, 0u);
        return false;
    }
    err = f_write(&bb_img, data, BB_SD_SECTOR, &written);
    if (err != FR_OK || written != BB_SD_SECTOR) {
        ++bb_write_errors;
        bb_sd_io_diag("write-failed", sector, err, written);
        return false;
    }
    err = f_sync(&bb_img);
    if (err != FR_OK) {
        ++bb_write_errors;
        bb_sd_io_diag("sync-failed", sector, err, written);
        return false;
    }
    ++bb_write_count;
    if (bb_write_count <= 5u || bb_write_count % 64u == 0u)
        printf("[bb-sd] persisted LBA=%lu writes=%lu\n",
               (unsigned long)sector, bb_write_count);
    return true;
}

/* BB_STAGE2B_C_READONLY
 * 16 MiB FAT16 backing file. All read traffic uses FatFs, not guest PSRAM.
 * The SPI1 baud rate must be reset after LCD changes clk_peri.
 */

/* BB_STAGE2D_C_READ_CACHE
 * Four clean sectors (2 KiB). Never cache dirty data, never delay f_sync.
 * No card/image sharing with another USB mass storage host while mounted.
 */
#define BB_C_CACHE_COUNT 4u
typedef struct {
    uint32_t sector;
    uint32_t age;
    bool valid;
    uint8_t bytes[512];
} bb_c_cache_entry;
static bb_c_cache_entry bb_c_cache[BB_C_CACHE_COUNT];
static uint32_t bb_c_cache_age;
static unsigned long bb_c_cache_hit, bb_c_cache_miss, bb_c_cache_invalid;

static void bb_c_cache_reset(void)
{
    unsigned i;
    for (i = 0; i < BB_C_CACHE_COUNT; ++i) bb_c_cache[i].valid = false;
    bb_c_cache_age = 0u;
    bb_c_cache_hit = bb_c_cache_miss = bb_c_cache_invalid = 0u;
}
static void bb_c_cache_invalidate(uint32_t sector)
{
    unsigned i;
    for (i = 0; i < BB_C_CACHE_COUNT; ++i) {
        if (bb_c_cache[i].valid && bb_c_cache[i].sector == sector) {
            bb_c_cache[i].valid = false;
            ++bb_c_cache_invalid;
        }
    }
}
static bool bb_c_cache_lookup(uint32_t sector, uint8_t *out)
{
    unsigned i;
    for (i = 0; i < BB_C_CACHE_COUNT; ++i) {
        if (bb_c_cache[i].valid && bb_c_cache[i].sector == sector) {
            memcpy(out, bb_c_cache[i].bytes, 512u);
            bb_c_cache[i].age = ++bb_c_cache_age;
            ++bb_c_cache_hit;
            return true;
        }
    }
    ++bb_c_cache_miss;
    return false;
}
static void bb_c_cache_insert(uint32_t sector, const uint8_t *data)
{
    unsigned i, victim=0u;
    for (i = 0u; i < BB_C_CACHE_COUNT; ++i) {
        if (!bb_c_cache[i].valid) { victim=i; break; }
        if (bb_c_cache[i].age < bb_c_cache[victim].age) victim=i;
    }
    bb_c_cache[victim].sector=sector;
    bb_c_cache[victim].age=++bb_c_cache_age;
    memcpy(bb_c_cache[victim].bytes, data, 512u);
    bb_c_cache[victim].valid=true;
}

bool bb_sd_c_available(void) { return bb_c_open; }
bool bb_sd_c_read_sector(uint32_t sector, uint8_t *data, size_t size)
{
    FRESULT fr;
    UINT got = 0u;
    static unsigned count;
    if (!bb_c_open || !data || size != 512u || sector >= 32768u) return false;
    if (bb_c_cache_lookup(sector, data)) return true;
    (void)spi_set_baudrate(spi1, 12500000u);
    fr = f_lseek(&bb_c_img, (FSIZE_t)sector * 512u);
    if (fr == FR_OK) fr = f_read(&bb_c_img, data, 512u, &got);
    if (fr != FR_OK || got != 512u) {
        printf("[bb-sd-c] read-failed lba=%lu fr=%d got=%u\n",
               (unsigned long)sector, (int)fr, (unsigned)got);
        return false;
    }
    bb_c_cache_insert(sector, data);
    if (++count <= 8u) printf("[bb-sd-c] read lba=%lu OK (cache h=%lu m=%lu)\n",
        (unsigned long)sector, bb_c_cache_hit, bb_c_cache_miss);
    return true;
}


/* BB_STAGE2C_C_WRITABLE
 * DOS unit 2 -> FAT16 image sector write-through. Conservative first release:
 * 512 bytes per transaction; FatFs f_sync before acknowledging DOS success.
 * Never writes the host FAT32 filesystem outside DRIVE_C.IMG.
 * No PSRAM image copy and no cache needed for correctness.
 */
bool bb_sd_c_write_sector(uint32_t sector, const uint8_t *data, size_t size)
{
    static unsigned long writes, errors;
    FRESULT fr;
    UINT wrote = 0u;
    if (!bb_c_open || !data || size != 512u || sector >= 32768u) return false;
    /* LCD retunes clk_peri to 150 MHz after the card is initialized. */
    (void)spi_set_baudrate(spi1, 12500000u);
    fr = f_lseek(&bb_c_img, (FSIZE_t)sector * 512u);
    if (fr != FR_OK) {
        ++errors;
        printf("[bb-sd-c] WRITE ERROR stage=seek lba=%lu fr=%d errors=%lu\n",
               (unsigned long)sector, (int)fr, errors);
        return false;
    }
    /* Invalidate before modifying backing storage, including on failure. */
    bb_c_cache_invalidate(sector);
    fr = f_write(&bb_c_img, data, 512u, &wrote);
    if (fr != FR_OK || wrote != 512u) {
        ++errors;
        printf("[bb-sd-c] WRITE ERROR stage=write lba=%lu fr=%d wrote=%u errors=%lu\n",
               (unsigned long)sector, (int)fr, (unsigned)wrote, errors);
        return false;
    }
    fr = f_sync(&bb_c_img);
    if (fr != FR_OK) {
        ++errors;
        printf("[bb-sd-c] WRITE ERROR stage=sync lba=%lu fr=%d wrote=%u errors=%lu\n",
               (unsigned long)sector, (int)fr, (unsigned)wrote, errors);
        return false;
    }
    ++writes;
    if (writes <= 12u || writes % 64u == 0u)
        printf("[bb-sd-c] persisted lba=%lu writes=%lu\n",
               (unsigned long)sector, writes);
    return true;
}

static bool bb_generic_b_open;
static bool bb_sd_b_read_generic(uint32_t, uint8_t *, size_t);
/* BB_DESCENT_VFLOPPY_B_V1
 * Read-only 1.44 MiB FAT12 floppy image for DOS unit 1 (B:).
 * Selection: /BLITZBUS/B_DISK.TXT one digit 1..5; reboot to change.
 * Reads are NOT cached, and disk images are NEVER modified.
 */
bool bb_sd_b_available(void) { return true; }
bool bb_sd_b_read_sector(uint32_t sector, uint8_t *data, size_t size)
{
    FRESULT fr;
    UINT got=0u;
    static unsigned long reads;
    if (bb_generic_b_open) return bb_sd_b_read_generic(sector,data,size);
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

/* BB_GENERIC_DISK_V1: read-only B: backed by SD FAT or nested FAT16 C: file. */
static FIL bb_generic_b_file;
static bool bb_generic_b_open = false;
static bool bb_generic_b_nested = false;
static uint16_t bb_generic_start_cluster, bb_generic_last_cluster;
static uint32_t bb_generic_last_cluster_index;
static uint16_t bb_generic_c_spc, bb_generic_c_spfat, bb_generic_c_reserved, bb_generic_c_root_entries;
static uint8_t bb_generic_c_fats;
static uint32_t bb_generic_c_data_lba, bb_generic_c_root_lba;

static uint16_t bb_gen_u16(const uint8_t *s) { return (uint16_t)(s[0] | ((unsigned)s[1] << 8)); }
static uint32_t bb_gen_u32(const uint8_t *s) { return (uint32_t)s[0] | ((uint32_t)s[1]<<8) | ((uint32_t)s[2]<<16) | ((uint32_t)s[3]<<24); }
static bool bb_gen_sector(uint32_t sector, uint8_t *buffer) {
    return bb_sd_c_read_sector(sector, buffer, 512u);
}
static bool bb_gen_fat(uint16_t cluster, uint16_t *next) {
    uint8_t sector[512];
    if (!bb_gen_sector((uint32_t)bb_generic_c_reserved + ((uint32_t)cluster * 2u)/512u,sector)) return false;
    *next=bb_gen_u16(sector+((cluster*2u)%512u));
    return *next>=2u && *next<0xFFF7u || *next>=0xFFF8u;
}
static bool bb_gen_nth(uint16_t start, uint32_t index, uint16_t *result) {
    uint16_t cur=start;
    uint32_t i=0;
    if (start<2u) return false;
    if (start==bb_generic_start_cluster && index>=bb_generic_last_cluster_index && bb_generic_last_cluster>=2u) {
        i=bb_generic_last_cluster_index;cur=bb_generic_last_cluster;
    }
    while (i<index) {
        uint16_t next;
        if (!bb_gen_fat(cur,&next) || next>=0xFFF8u) return false;
        cur=next;++i;
    }
    bb_generic_last_cluster_index=index;bb_generic_last_cluster=cur;
    *result=cur;return true;
}
static bool bb_gen_entry(uint32_t first_sector, uint32_t sectors, const uint8_t name[11], uint8_t out[32]) {
    uint8_t sector[512];uint32_t s;
    for(s=0;s<sectors;s++) {
        unsigned i;
        if (!bb_gen_sector(first_sector+s,sector))return false;
        for (i=0;i<16u;i++) {
            const uint8_t *e=sector+32u*i;
            if (e[0]==0) return false;
            if (e[0]==0xE5u || (e[11]&0x0Fu)==0x0Fu || (e[11]&8u))continue;
            if (memcmp(e,name,11u)==0) { memcpy(out,e,32u);return true; }
        }
    }
    return false;
}
static bool bb_gen_name(const char *name, size_t len, uint8_t out[11]) {
    unsigned i=0u,j=0u;bool ext=false;
    if (!len)return false;
    memset(out,' ',11u);
    while (len--) {
        char c=*name++;
        if (c=='.' && !ext) {ext=true;continue;}
        if (c==' ' || c=='/' || c=='\\' || c==':' || c=='.')return false;
        if (c>='a' && c<='z') c=(char)(c-32);
        if (!((c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='$'||c=='~'))return false;
        if (!ext) {if(i>=8u)return false;out[i++]=(uint8_t)c;}
        else {if(j>=3u)return false;out[8u+j++]=(uint8_t)c;}
    }
    return i!=0u;
}
static bool bb_gen_c_lookup(const char *dospath) {
    uint8_t sector[512],entry[32];
    uint16_t current=0u;
    const char *p=dospath;
    unsigned depth=0u;
    if (!bb_gen_sector(0u,sector))return false;
    if(bb_gen_u16(sector+11u)!=512u || sector[13u]==0u)return false;
    bb_generic_c_spc=sector[13u]; bb_generic_c_reserved=bb_gen_u16(sector+14u);
    bb_generic_c_fats=sector[16u];bb_generic_c_root_entries=bb_gen_u16(sector+17u);
    bb_generic_c_spfat=bb_gen_u16(sector+22u);
    bb_generic_c_root_lba=(uint32_t)bb_generic_c_reserved+(uint32_t)bb_generic_c_fats*bb_generic_c_spfat;
    bb_generic_c_data_lba=bb_generic_c_root_lba+((uint32_t)bb_generic_c_root_entries*32u+511u)/512u;
    if(!bb_generic_c_fats || !bb_generic_c_spfat)return false;
    while(*p=='/' || *p=='\\')++p;
    while(*p && depth++<24u) {
        const char *b=p;
        uint8_t name[11];bool final;
        uint32_t sectors,first;
        while(*p && *p!='/' && *p!='\\')++p;
        if(!bb_gen_name(b,(size_t)(p-b),name))return false;
        while(*p=='/' || *p=='\\')++p;
        final=(*p==0);
        if(current==0u) {
            first=bb_generic_c_root_lba;sectors=((uint32_t)bb_generic_c_root_entries*32u+511u)/512u;
            if(!bb_gen_entry(first,sectors,name,entry))return false;
        } else {
            uint16_t cl=current;
            bool found=false;
            unsigned guards=0u;
            do {
                uint16_t next;
                first=bb_generic_c_data_lba+(uint32_t)(cl-2u)*bb_generic_c_spc;
                if(bb_gen_entry(first,bb_generic_c_spc,name,entry)) {found=true;break;}
                if(!bb_gen_fat(cl,&next)||next>=0xFFF8u)break;
                cl=next;
            } while(++guards<8192u);
            if(!found)return false;
        }
        current=bb_gen_u16(entry+26u);
        if(final) {
            if ((entry[11u]&0x10u) || bb_gen_u32(entry+28u)!=1474560u || current<2u)return false;
            bb_generic_start_cluster=current;
            bb_generic_last_cluster=0;
            bb_generic_last_cluster_index=0;
            return true;
        }
        if(!(entry[11u]&0x10u)||current<2u)return false;
    }
    return false;
}
bool bb_sd_b_select_path(const char *path)
{
    FRESULT fr;
    char full[160];
    bool nested=false;
    const char *p=path;
    if(!path || !bb_img_open)return false;
    if ((p[0]=='S'||p[0]=='s')&&(p[1]=='D'||p[1]=='d')&&p[2]==':')p+=3;
    else if ((p[0]=='C'||p[0]=='c')&&p[1]==':') {p+=2;nested=true;}
    else {printf("[bb-disk] path needs SD: or C: prefix\n");return false;}
    if(!*p)return false;
    if (!nested) {
        size_t n=0u;
        full[n++]='0';full[n++]=':';full[n++]='/';
        while (*p && n<sizeof(full)-1u) {char c=*p++;full[n++]=c=='\\' ? '/' : c;}
        if (*p)return false;
        full[n]=0;
        if(bb_generic_b_open && !bb_generic_b_nested) (void)f_close(&bb_generic_b_file);
        bb_generic_b_open=false;
        (void)spi_set_baudrate(spi1,12500000u);
        fr=f_open(&bb_generic_b_file,full,FA_READ);
        if(fr!=FR_OK) {printf("[bb-disk] SD open failed fr=%d %s\n",(int)fr,full);return false;}
        if(f_size(&bb_generic_b_file)!=1474560u) {
            printf("[bb-disk] unsupported image size %lu (need 1474560)\n",(unsigned long)f_size(&bb_generic_b_file));
            (void)f_close(&bb_generic_b_file);return false;
        }
    } else if(!bb_gen_c_lookup(p)) {
        printf("[bb-disk] C: image not found / invalid FAT16 chain: %s\n",p);
        return false;
    }
    bb_generic_b_open=true;bb_generic_b_nested=nested;
    printf("[bb-disk] mounted B: %s (read-only)\n",path);
    return true;
}
static bool bb_sd_b_read_generic(uint32_t lba,uint8_t *data,size_t size)
{
    FRESULT fr;UINT got=0u;
    if(!bb_generic_b_open || !data || size!=512u || lba>=2880u)return false;
    if(!bb_generic_b_nested) {
        (void)spi_set_baudrate(spi1,12500000u);
        fr=f_lseek(&bb_generic_b_file,(FSIZE_t)lba*512u);
        return fr==FR_OK && f_read(&bb_generic_b_file,data,512u,&got)==FR_OK && got==512u;
    } else {
        uint16_t cluster;
        uint32_t cl_index=lba/bb_generic_c_spc;
        if(!bb_gen_nth(bb_generic_start_cluster,cl_index,&cluster))return false;
        return bb_gen_sector(bb_generic_c_data_lba+(uint32_t)(cluster-2u)*bb_generic_c_spc+(lba%bb_generic_c_spc),data);
    }
}

/* BB_GENERIC_DISK_V1 */
