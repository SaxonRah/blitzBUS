/* C11 mock of the complete installed .inc; asserts SPI1 divider is reset
   BEFORE any FatFs I/O after LCD clock shift, plus error reporting. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define FA_READ 1
#define FR_OK 0
#define FR_DISK_ERR 1
#define clk_peri 1
#define spi1 ((void *)0x1234)
typedef unsigned UINT;
typedef unsigned long FSIZE_t;
typedef int FRESULT;
typedef struct { FSIZE_t pos, size; } FIL;
static uint32_t baud = 37500000u;
static unsigned retimes, seeks, reads, failures;
static uint32_t spi_get_baudrate(void *id) { assert(id == spi1); return baud; }
static uint32_t spi_set_baudrate(void *id, uint32_t requested) {
    assert(id == spi1); assert(requested == 12500000u);
    ++retimes; return baud = 12500000u;
}
static uint32_t clock_get_hz(int id) { assert(id == clk_peri); return 150000000u; }
static FRESULT f_open(FIL *f, const char *path, int flags) {
    (void)f;(void)path;(void)flags;return FR_DISK_ERR;
}
static FRESULT f_close(FIL *f) { (void)f; return FR_OK; }
static FRESULT f_lseek(FIL *f, FSIZE_t off) {
    assert(baud == 12500000u); ++seeks; f->pos=off;
    return failures == 1 ? FR_DISK_ERR : FR_OK;
}
static FRESULT f_read(FIL *f, void *dst, UINT count, UINT *got) {
    assert(baud == 12500000u); ++reads; (void)f;
    if (failures == 2) { *got=0; return FR_DISK_ERR; }
    memset(dst, 0xA5, count); *got=count; return FR_OK;
}
static FSIZE_t f_size(FIL *f) { return f->size; }
#include "bb_dos622_sd.inc"
int main(void) {
    uint8_t dst[512];
    bb622_mount("0:"); assert(!bb_sd_dos622_active());
    bb622_disk_open = true; bb622_disk.size = 1474560u;
    assert(bb_sd_dos622_read_sector(0, dst, sizeof dst));
    assert(seeks == 1 && reads == 1 && retimes == 1);
    for (unsigned i=0;i<sizeof dst;i++) assert(dst[i]==0xA5);
    assert(bb_sd_dos622_read_sector(2879, dst, sizeof dst));
    assert(bb622_disk.pos == (FSIZE_t)2879*512);
    assert(!bb_sd_dos622_read_sector(2880, dst, sizeof dst));
    assert(retimes == 2 && seeks == 2);
    failures = 1; assert(!bb_sd_dos622_read_sector(12, dst, sizeof dst));
    assert(retimes == 3 && seeks == 3 && reads == 2);
    failures = 2; assert(!bb_sd_dos622_read_sector(13, dst, sizeof dst));
    assert(retimes == 4 && seeks == 4 && reads == 3);
    assert(bb622_read_errors == 2 && bb622_read_calls == 2);
    puts("BB DOS622 CLOCKFIX PASS: SPI1 retimed before seek/read; LBA bounds; seek/read errors");
}
