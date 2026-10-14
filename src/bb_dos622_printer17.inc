/* BB_DOS622_PRINTER17_V1
 * BIOS INT 17h / printer interface. No LPT ports are installed or
 * advertised (equipment word printer count = zero).
 *
 * AH=00 write character, AH=01 initialize printer, AH=02 get status.
 * Return AH=01 (bit 0: timed out / absent printer) and preserve AL.
 * No electrical port I/O and no use of the Pico USB console as LPT.
 * This handler exists only in the opt-in DOS 6.22 BIOS.
 */
static bool BB622_FLASH bb622_printer17(MdRuntime *rt)
{
    MdX86 *c = &rt->cpu;
    const uint16_t input_ax = c->r[MD_X86_AX];
    const uint16_t unit = c->r[MD_X86_DX];
    const uint8_t fn = (uint8_t)(input_ax >> 8);
    static uint32_t calls;
    /* AH status bit 0: timeout. The input low byte is preserved even for
       initialize/status queries. No physical printer is present. */
    c->r[MD_X86_AX] = (uint16_t)(0x0100u | (input_ax & 0x00ffu));
    if (++calls <= 12u) {
        printf("[bb622-printer17] no LPT%u fn=%02X in-ax=%04X out-ax=%04X (timeout)\n",
               (unsigned)(unit + 1u), (unsigned)fn,
               (unsigned)input_ax, (unsigned)c->r[MD_X86_AX]);
        fflush(stdout);
    }
    return true;
}
