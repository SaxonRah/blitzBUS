/* BB_DOS622_IPL_V1 - optional separate MS-DOS 6.x boot floppy from SD.
   This code intentionally never modifies the established BOOT.IMG path. */
static FIL bb622_disk;
static bool bb622_disk_open;
static uint32_t bb622_read_calls;
static uint32_t bb622_read_errors;

bool bb_sd_dos622_active(void) { return bb622_disk_open; }

bool bb_sd_dos622_read_sector(uint32_t lba, uint8_t *dst, size_t length)
{
    FRESULT rc;
    UINT got = 0;
    if (!bb622_disk_open || !dst || length != 512u || lba >= 2880u) return false;
    rc = f_lseek(&bb622_disk, (FSIZE_t)lba * 512u);
    if (rc != FR_OK) { ++bb622_read_errors; return false; }
    rc = f_read(&bb622_disk, dst, 512u, &got);
    if (rc != FR_OK || got != 512u) {
        ++bb622_read_errors;
        if (bb622_read_errors <= 8u) printf("[bb-dos622] disk READ ERROR lba=%lu fr=%d bytes=%u\n",
                                              (unsigned long)lba, (int)rc, (unsigned)got);
        return false;
    }
    ++bb622_read_calls;
    if (bb622_read_calls <= 8u) printf("[bb-dos622] read lba=%lu OK\n", (unsigned long)lba);
    return true;
}

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
