/* BB_DOS622_TEXTIO_V1
 * DOS 6.22-only USB keyboard / B800 text mirror.  SRAM rescue V1:
 * Keep the snapshot bookkeeping in PSRAM because bb_live.c has 4096-byte
 * aligned buffers further below this include; even a small SRAM .bss
 * insertion can increase the linker's alignment padding by 4096 bytes.
 * The screen itself always remains guest memory, never copied wholesale.
 */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
extern bool bb_sd_dos622_active(void);
/* BB_DOS622_TEXTIO_PSRAM_V1 */
typedef struct Bb622TextIOState {
    uint64_t sample_us;
    uint32_t row_hash[25];
    uint8_t row_visible[25];
    unsigned announced;
} Bb622TextIOState;
static Bb622TextIOState __uninitialized_psram("bb622_textio") bb622_textio_state;

/* Explicitly clear the uninitialized PSRAM section on each DOS622 start.
 * Do not rely on zeroed PSRAM after soft reset or BOOTSEL. */
static void bb622_textio_reset(void)
{
    memset(&bb622_textio_state, 0, sizeof bb622_textio_state);
}

static void bb622_textio_mirror(MdRuntime *rt)
{
    if (!rt || !bb_sd_dos622_active() || bb_video_seen || bb_vga_active()) return;
    Bb622TextIOState *s = &bb622_textio_state;
    const uint64_t now = bb_now_us();
    if (s->sample_us && now - s->sample_us < 250000ull) return;
    s->sample_us = now;
    if (!s->announced) {
        s->announced = 1u;
        printf("[bb622-textio] MS-DOS 6.22 text-mode USB keyboard + B800 serial mirror enabled (state PSRAM)\n");
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
        if (h == s->row_hash[row]) continue;
        s->row_hash[row] = h;
        if (!end) {
            if (s->row_visible[row]) {
                printf("[bb622-screen] row=%02u (cleared)\n", row);
                s->row_visible[row] = 0u;
            }
        } else {
            printf("[bb622-screen] row=%02u |%s|\n", row, chars);
            s->row_visible[row] = 1u;
        }
    }
    fflush(stdout);
}
#else
static void bb622_textio_reset(void) {}
static void bb622_textio_mirror(MdRuntime *rt) { (void)rt; }
#endif
