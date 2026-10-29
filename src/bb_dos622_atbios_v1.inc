/* BB_DOS622_ATBIOS_V1: DOS 6.22 VGA text BIOS compatibility.
 * Included by bb_live.c AFTER bb_vga.c (which owns the emulated text page).
 * Only run for the real DOS622.IMG boot. Nothing here claims extended memory.
 *
 * Services:
 *   INT 10h AX=1104/1114, BL=00: restore default 8x16 character geometry.
 *   INT 10h AH=13h, AL=00..03: write text to page 0, modes 03h only.
 *
 * IMPORTANT: the existing LCD/B800 text renderer already uses its fixed
 * character raster. This restores text-mode geometry and cursor state,
 * NOT VGA plane-2 font RAM. Do not advertise BIOS 1130h ROM font pointers
 * until the guest has real readable ROM font tables.
 */
#ifndef BB_DOS622_ATBIOS_V1_INC
#define BB_DOS622_ATBIOS_V1_INC
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
extern bool bb_sd_dos622_active(void);
static unsigned bb622_at_font_calls, bb622_at_string_calls;
static int bb622_at_vga_int10(uint16_t *ax, uint16_t *bx, uint16_t *cx,
                              uint16_t *dx, uint16_t *es, uint16_t *bp,
                              uint16_t *flags)
{
    const unsigned ah = (unsigned)(*ax >> 8);
    const unsigned al = (unsigned)(*ax & 255u);
    (void)flags;
    if (!bb_sd_dos622_active()) return 0;
    if (ah == 0x11u && (al == 0x04u || al == 0x14u)) {
        /* Supported geometry: 80x25 VGA mode 3, single installed font block.
         * Other block selectors require VGA plane-2 font storage. */
        if (mode != 3u || (*bx & 255u) != 0u) return 0;
        bb_v34_note(0x440u,0x50u); /* BB_V34_HOSTWRITE_V1 geometry BDA */
        mem[0x484u] = 24u;           /* highest displayed row */
        mem[0x485u] = 16u;           /* bytes/character on display */
        cursor_shape = 0x0607u;
        mem[0x460u] = 0x07u;         /* BDA cursor start/end */
        mem[0x461u] = 0x06u;
        /* Do not call set_mode(): it would destroy the visible DOS screen. */
        if (++bb622_at_font_calls <= 8u) {
            printf("[bb622-atbios] INT10 AX=%04X BL=00 VGA 8x16 text geometry restored\n", (unsigned)*ax);
            fflush(stdout);
        }
        return 1;                   /* AX unchanged: BIOS specifies no output */
    }
    if (ah == 0x13u && al <= 3u) {
        /* BIOS text string: BH=page, BL=attribute, CX=character count,
         * DH:DL=starting row:col, ES:BP=chars or char/attr pairs.
         * Support real mode 03h/page 0 only, so do not claim other pages. */
        unsigned row = (unsigned)(*dx >> 8), col = (unsigned)(*dx & 255u);
        const unsigned paired = (al & 2u) != 0u;
        const unsigned update_cursor = (al & 1u) != 0u;
        const unsigned attr_default = (unsigned)(*bx & 255u);
        if (mode != 3u || (*bx >> 8) != 0u || row > 24u || col > 79u)
            return 0;
        bb_v34_note(0xB8000u,4000u); /* BB_V34_HOSTWRITE_V1 text string */
        const uint16_t previous_cursor = cursor[0];
        for (unsigned i = 0; i < (unsigned)*cx; ++i) {
            const uint16_t o = (uint16_t)(*bp + (uint16_t)(i * (paired ? 2u : 1u)));
            const uint8_t c = mread(*es, o);
            const uint8_t attribute = paired ? mread(*es, (uint16_t)(o + 1u)) : (uint8_t)attr_default;
            if (c == 13u) { col = 0u; continue; }
            if (c == 10u) { ++row; }
            else if (c == 8u) { if (col) --col; continue; }
            else if (c != 7u) {
                unsigned off = 0xB8000u + (row * 80u + col) * 2u;
                if (row < 25u) { mem[off] = c; mem[off + 1u] = attribute; }
                if (++col == 80u) { col = 0u; ++row; }
            }
            if (row >= 25u) {
                scroll_text(0u, 0u, 24u, 79u, 1u, 7u, 0);
                row = 24u;
            }
        }
        if (update_cursor) cursor[0] = (uint16_t)((row << 8) | col);
        else cursor[0] = previous_cursor;
        video_bda();
        if (++bb622_at_string_calls <= 4u) {
            printf("[bb622-atbios] INT10 AH=13 AL=%02X count=%u cursor=%04X\n",
                   al, (unsigned)*cx, (unsigned)cursor[0]);
            fflush(stdout);
        }
        return 1;
    }
    return 0;
}
#else
static int bb622_at_vga_int10(uint16_t *ax, uint16_t *bx, uint16_t *cx,
                              uint16_t *dx, uint16_t *es, uint16_t *bp,
                              uint16_t *flags)
{
    (void)ax; (void)bx; (void)cx; (void)dx; (void)es; (void)bp; (void)flags;
    return 0;
}
#endif
#endif
