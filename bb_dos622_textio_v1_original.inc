/* BB_DOS622_TEXTIO_V1
 * Serial observer for guest IBM PC color text RAM at B800:0000.
 * This does not replace VGA hardware, DOS CON, or alter the x86 CPU.
 * Active only when the opt-in DOS622 image is mounted and the existing
 * legacy mode-13h input/presenter path is not active.
 */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
extern bool bb_sd_dos622_active(void);
static uint64_t bb622_textio_sample_us;
static uint32_t bb622_textio_row_hash[25];
static uint8_t bb622_textio_row_visible[25];
static unsigned bb622_textio_announced;
static void bb622_textio_mirror(MdRuntime *rt)
{
    if (!rt || !bb_sd_dos622_active() || bb_video_seen || bb_vga_active()) return;
    const uint64_t now = bb_now_us();
    if (bb622_textio_sample_us && now - bb622_textio_sample_us < 250000ull) return;
    bb622_textio_sample_us = now;
    if (!bb622_textio_announced) {
        bb622_textio_announced = 1u;
        printf("[bb622-textio] MS-DOS 6.22 text-mode USB keyboard + B800 serial mirror enabled\n");
        fflush(stdout);
    }
    const uint8_t *p = rt->cpu.memory + 0xB8000u;
    for (unsigned row = 0; row < 25u; ++row) {
        char chars[81];
        uint32_t h = 2166136261u;
        unsigned end = 0;
        for (unsigned col = 0; col < 80u; ++col) {
            unsigned c = p[(row * 80u + col) * 2u];
            char ch = (c >= 0x20u && c <= 0x7Eu) ? (char)c : ' ';
            chars[col] = ch;
            h = (h ^ (uint8_t)ch) * 16777619u;
            if (ch != ' ') end = col + 1u;
        }
        chars[end] = '\0';
        if (h == bb622_textio_row_hash[row]) continue;
        bb622_textio_row_hash[row] = h;
        if (!end) {
            if (bb622_textio_row_visible[row]) {
                printf("[bb622-screen] row=%02u (cleared)\n", row);
                bb622_textio_row_visible[row] = 0u;
            }
        } else {
            printf("[bb622-screen] row=%02u |%s|\n", row, chars);
            bb622_textio_row_visible[row] = 1u;
        }
    }
    fflush(stdout);
}
#else
static void bb622_textio_mirror(MdRuntime *rt) { (void)rt; }
#endif
