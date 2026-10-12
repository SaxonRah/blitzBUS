/* blitzBUS Stage 1 SD boot image loader.
 * SPI1 wiring is provided by bb_sd_hw.c (microconsole LCD microSD slot).
 * This reads one 360 KiB FAT12 image into PSRAM; DOS writes remain volatile.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "ff.h"
#include "diskio.h"
#include "hw_config.h"
#include "sd_card.h"

bool bb_sd_boot_image(uint8_t *dest, unsigned bytes)
{
    sd_card_t *sd;
    const char *drive;
    FIL file;
    char image_path[96];
    UINT got;
    FRESULT err;
    unsigned offset;

    if (dest == NULL || bytes != 368640u) {
        printf("[bb-sd] invalid destination or size=%u (embedded fallback)\n", bytes);
        return false;
    }
    /* The pico-fatfs-sd library requires its SPI/GPIO initialization before
       FatFs can mount a volume.  This is also how microconsole FastDoom boots. */
    if (!sd_init_driver()) {
        printf("[bb-sd] sd_init_driver failed (embedded fallback)\n");
        return false;
    }
    sd = sd_get_by_num(0u);
    if (sd == NULL) {
        printf("[bb-sd] sd_get_by_num(0) failed (embedded fallback)\n");
        return false;
    }
    drive = sd_get_drive_prefix(sd);
    if (drive == NULL) {
        printf("[bb-sd] missing SD drive prefix (embedded fallback)\n");
        return false;
    }
    printf("[bb-sd-prelcd] start raw-status=0x%02x card-type=%d\n",
           (unsigned)disk_status(0u), (int)sd->state.card_type);
    err = f_mount(&sd->state.fatfs, drive, 1u);
    if (err != FR_OK) {
        printf("[bb-sd-prelcd] mount failed=%d status=0x%02x card-type=%d prefix=%s (embedded fallback)\n",
               (int)err, (unsigned)disk_status(0u), (int)sd->state.card_type, drive);
        return false;
    }
    sd->state.mounted = true;
    if (snprintf(image_path, sizeof(image_path), "%s/BLITZBUS/BOOT.IMG", drive) >= (int)sizeof(image_path)) {
        printf("[bb-sd] image path too long (embedded fallback)\n");
        return false;
    }
    err = f_open(&file, image_path, FA_READ);
    if (err != FR_OK) {
        printf("[bb-sd] BOOT.IMG open failed=%d (embedded fallback)\n", (int)err);
        return false;
    }
    if (f_size(&file) != (FSIZE_t)bytes) {
        printf("[bb-sd] invalid BOOT.IMG size=%lu expected=%u (embedded fallback)\n",
               (unsigned long)f_size(&file), bytes);
        (void)f_close(&file);
        return false;
    }
    offset = 0u;
    while (offset < bytes) {
        const UINT want = (bytes - offset) > 4096u ? 4096u : (UINT)(bytes - offset);
        got = 0u;
        err = f_read(&file, dest + offset, want, &got);
        if (err != FR_OK || got != want) {
            printf("[bb-sd] read failed offset=%u err=%d got=%u expected=%u (embedded fallback)\n",
                   offset, (int)err, got, want);
            (void)f_close(&file);
            return false;
        }
        offset += got;
    }
    err = f_close(&file);
    if (err != FR_OK) {
        printf("[bb-sd] close failed=%d (embedded fallback)\n", (int)err);
        return false;
    }
    printf("[bb-sd] A: BOOT.IMG loaded %u bytes into PSRAM; writes are volatile\n", bytes);
    return true;
}
