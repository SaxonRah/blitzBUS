/* BB_DOS622_SERIAL14_GUARD_V1
 * Real-mode BIOS INT 14h: no installed serial adapters.  The BIOS data area
 * advertises zero COM ports and the virtual UART is not implemented.
 * Do not map this service to the Pico's USB console.  Return a documented
 * timeout/no-device status instead of dispatching IVT 0014:0000 (zero).
 *
 * Code stays in flash; one 4-byte diagnostic counter uses SRAM.  JIT unchanged.
 */
static bool BB622_FLASH bb622_serial14(MdRuntime *rt)
{
    MdX86 *c = &rt->cpu;
    const uint16_t old_ax = c->r[MD_X86_AX];
    const uint8_t fn = (uint8_t)(old_ax >> 8);
    const uint16_t port = c->r[MD_X86_DX];
    static uint32_t calls;
    /* AH=80h: serial line timed out / device absent.  BIOS INT 14h
       functions 00/03 return AL modem status; 01 preserves transmitted AL.
       No serial port is advertised by the machine's BDA/equipment word. */
    c->r[MD_X86_AX] = (uint16_t)(0x8000u | (fn == 1u ? (old_ax & 0x00ffu) : 0u));
    if (++calls <= 12u) {
        printf("[bb622-serial14] no COM%u fn=%02X in-ax=%04X out-ax=%04X (timeout)\n",
               (unsigned)(port + 1u), (unsigned)fn, (unsigned)old_ax,
               (unsigned)c->r[MD_X86_AX]);
        fflush(stdout);
    }
    return true; /* no fallthrough into a null guest IVT */
}

/* Only protects firmware interrupt vectors in real DOS622 mode.
 * Actual guest-installed vector handlers are still dispatched normally.
 * The boot path does not claim DOS INT 21h or other OS-owned vectors.
 * An unsupported BIOS service is a reportable stop, not a silent jump into
 * 0000:0000 followed by millions of spurious zero-byte instructions.
 */
static bool BB622_FLASH bb622_null_firmware_vector(MdRuntime *rt, uint8_t vector)
{
    MdX86 *c = &rt->cpu;
    const uint16_t ofs = (uint16_t)((uint16_t)vector * 4u);
    if (vector < 0x10u || vector > 0x1fu) return false;
    if (md_x86_read16(c, 0u, ofs) != 0u ||
        md_x86_read16(c, 0u, (uint16_t)(ofs + 2u)) != 0u) return false;
    printf("[bb622-missing-bios] unhandled INT %02X AX=%04X BX=%04X CX=%04X DX=%04X at=%04X:%04X; null IVT, stopping safely\n",
           (unsigned)vector, (unsigned)c->r[MD_X86_AX],
           (unsigned)c->r[MD_X86_BX], (unsigned)c->r[MD_X86_CX],
           (unsigned)c->r[MD_X86_DX], (unsigned)c->cs, (unsigned)c->ip);
    fflush(stdout);
    rt->fault_linear = (((uint32_t)c->cs << 4u) + (uint32_t)c->ip) & 0xfffffu;
    rt->stop_reason = MD_STOP_FAULT;
    return true;
}
