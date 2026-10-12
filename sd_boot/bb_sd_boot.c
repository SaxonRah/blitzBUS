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
