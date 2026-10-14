/* BB_DOS622_IPL_V1 -- first PC BIOS services for an opt-in real DOS floppy.
   All functions are in flash; model=286 still retains the native Thumb-2 path.
   This is a first-stage BIOS, not yet a complete IBM PC AT implementation. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#define BB622_FLASH __attribute__((noinline,section(".text.bb622")))
extern bool bb_sd_dos622_active(void);
extern bool bb_sd_dos622_read_sector(uint32_t lba, uint8_t *dst, size_t size);
static uint8_t __uninitialized_psram("bb622_bios_sector") bb622_sector[512];
static uint8_t bb622_disk_status;
static uint32_t bb622_bios_reads;
static uint32_t bb622_bios_failed;

static void BB622_FLASH bb622_status(MdX86 *c, uint8_t status, uint8_t count)
{
    uint16_t f = md_x86_flags(c);
    c->r[MD_X86_AX] = (uint16_t)(((uint16_t)status << 8) | count);
    if (status) f |= MD_X86_FLAG_CF;
    else f &= (uint16_t)~MD_X86_FLAG_CF;
    md_x86_set_flags(c, f);
    bb622_disk_status = status;
}

static bool BB622_FLASH bb622_int13(MdRuntime *rt)
{
    MdX86 *c = &rt->cpu;
    const uint16_t ax = c->r[MD_X86_AX], cx = c->r[MD_X86_CX], dx = c->r[MD_X86_DX];
    const uint8_t fn = (uint8_t)(ax >> 8), count = (uint8_t)ax, drive = (uint8_t)dx;
    uint32_t lba, cylinder, sector, head, i;
    uint16_t flags;
    /* First milestone exposes only BIOS A:. C: is a DOS2 superfloppy and
       needs an MBR-compatible layout before announcing it as BIOS 80h. */
    if (fn == 0x00u) { bb622_status(c, drive == 0 ? 0u : 0x80u, 0u); return true; }
    if (fn == 0x01u) { bb622_status(c, bb622_disk_status, 0u); return true; }
    if (fn == 0x08u) {
        if (drive != 0u) { bb622_status(c, 0x80u, 0u); return true; }
        c->r[MD_X86_CX] = 0x4F12u; /* cylinder 79, 18 sectors/track */
        c->r[MD_X86_DX] = 0x0101u; /* head 1, 1 floppy drive */
        c->r[MD_X86_BX] = (uint16_t)((c->r[MD_X86_BX] & 0xFF00u) | 4u); /* 1.44MB */
        c->es = 0x0050u;
        c->r[MD_X86_DI] = 0x0100u;
        bb622_status(c, 0u, count); return true;
    }
    if (fn == 0x15u) {
        c->r[MD_X86_AX] = drive == 0u ? 0x0100u : 0x0000u; /* floppy / absent */
        flags = md_x86_flags(c); flags &= (uint16_t)~MD_X86_FLAG_CF;
        md_x86_set_flags(c, flags); return true; }
    if (fn == 0x16u) { bb622_status(c, drive == 0u ? 0u : 0x80u, 0u); return true; }
    if (fn == 0x03u || fn == 0x05u) { bb622_status(c, drive == 0u ? 0x03u : 0x80u, 0u); return true; } /* read-only */
    if (fn != 0x02u && fn != 0x04u) { bb622_status(c, 0x01u, 0u); return true; }
    if (drive != 0u) { bb622_status(c, 0x80u, 0u); return true; }
    cylinder = (uint32_t)(cx >> 8) | (((uint32_t)cx & 0xC0u) << 2);
    sector = (uint32_t)(cx & 0x3Fu);
    head = (uint32_t)(dx >> 8);
    if (count == 0 || cylinder >= 80u || head >= 2u || sector == 0u || sector > 18u) {
        bb622_status(c, 0x04u, 0u); return true;
    }
    lba = (cylinder * 2u + head) * 18u + sector - 1u;
    if (lba + count > 2880u) { bb622_status(c, 0x04u, 0u); return true; }
    /* The byte offset must fit the target 64KiB segment; reject DMA-boundary
       crossing in this first BIOS rather than silently wrapping ES:BX. */
    if ((uint32_t)c->r[MD_X86_BX] + (uint32_t)count * 512u > 65536u) {
        bb622_status(c, 0x09u, 0u); return true;
    }
    for (i = 0; i < count; ++i) {
        if (!bb_sd_dos622_read_sector(lba + i, bb622_sector, sizeof bb622_sector)) {
            ++bb622_bios_failed;
            bb622_status(c, 0x20u, (uint8_t)i); return true;
        }
        if (fn == 0x02u) md_x86_write_block(c, c->es,
                  (uint16_t)(c->r[MD_X86_BX] + i * 512u), bb622_sector, 512u);
        ++bb622_bios_reads;
    }
    bb622_status(c, 0u, count);
    return true;
}

static bool BB622_FLASH bb622_bios_interrupt(MdRuntime *rt, uint8_t vector, void *user)
{
    MdX86 *c = &rt->cpu;
    switch (vector) {
    case 0x13u: return bb622_int13(rt);
    case 0x11u: c->r[MD_X86_AX] = 0x0021u; return true; /* CGA, floppy */
    case 0x12u: c->r[MD_X86_AX] = 640u; return true;
    case 0x15u:
        if ((c->r[MD_X86_AX] >> 8) == 0x88u) {
            c->r[MD_X86_AX] = 0u; /* no extended RAM exposed yet */
            md_x86_set_flags(c, (uint16_t)(md_x86_flags(c) & ~MD_X86_FLAG_CF));
            return true;
        }
        c->r[MD_X86_AX] = (uint16_t)(0x86u << 8);
        md_x86_set_flags(c, (uint16_t)(md_x86_flags(c) | MD_X86_FLAG_CF));
        return true;
    case 0x1Au:
        if ((c->r[MD_X86_AX] >> 8) == 0x00u) {
            c->r[MD_X86_CX] = md_x86_read16(c, 0x0040u, 0x006Eu);
            c->r[MD_X86_DX] = md_x86_read16(c, 0x0040u, 0x006Cu);
            c->r[MD_X86_AX] &= 0xFF00u;
            md_x86_set_flags(c, (uint16_t)(md_x86_flags(c) & ~MD_X86_FLAG_CF));
            return true;
        }
        if ((c->r[MD_X86_AX] >> 8) == 0x01u) {
            md_x86_write16(c, 0x0040u, 0x006Eu, c->r[MD_X86_CX]);
            md_x86_write16(c, 0x0040u, 0x006Cu, c->r[MD_X86_DX]);
            md_x86_set_flags(c, (uint16_t)(md_x86_flags(c) & ~MD_X86_FLAG_CF));
            return true;
        }
        break;
    case 0x19u: /* BIOS bootstrap retry */
        return false; /* unsupported until reboot path is proven */
    default: break;
    }
    /* Important: do not claim DOS's INT 21h here. The real MSDOS.SYS
       must install and execute its own DOS API interrupt vectors. */
    return md_msdos2_boot_interrupt(rt, vector, user);
}

static bool BB622_FLASH bb622_boot_floppy(MdRuntime *rt)
{
    MdX86 *c = &rt->cpu;
    static const uint8_t dpt[11] = {0xDF,0x02,0x25,0x02,0x12,0x1B,0xFF,0x54,0xF6,0x0F,0x08};
    unsigned i;
    if (!bb_sd_dos622_active()) return false;
    if (!bb_sd_dos622_read_sector(0u, bb622_sector, sizeof bb622_sector)) return false;
    if (bb622_sector[510] != 0x55u || bb622_sector[511] != 0xAAu) return false;
    md_runtime_load_raw(rt, bb622_sector, 512u, 0x0000u, 0x7C00u);
    /* Preserve DOS2 kernel bytes for rollback; establish only BIOS BDA/IVT
       fields the genuine bootstrap immediately needs. */
    md_x86_write16(c, 0x0000u, 0x0078u, 0x0100u); /* INT1E floppy table */
    md_x86_write16(c, 0x0000u, 0x007Au, 0x0050u);
    for (i = 0; i < sizeof dpt; ++i) md_x86_write8(c, 0x0050u, (uint16_t)(0x0100u + i), dpt[i]);
    md_x86_write16(c, 0x0040u, 0x0010u, 0x0021u); /* equipment */
    md_x86_write16(c, 0x0040u, 0x0013u, 640u);    /* conventional KiB */
    md_x86_write8(c, 0x0040u, 0x0075u, 0u); /* hard disks advertised */
    c->cs = c->ds = c->es = c->ss = 0u;
    c->ip = 0x7C00u;
    c->r[MD_X86_SP] = 0x7C00u;
    c->r[MD_X86_DX] &= 0xFF00u; /* DL=00 BIOS A: */
    md_x86_set_flags(c, MD_X86_FLAG_ALWAYS1 | MD_X86_FLAG_IF);
    md_runtime_mark_code_range(rt, 0u, 0x7C00u, 512u);
    printf("[bb-dos622] ENTER real boot sector 0000:7C00, BIOS DL=00; image read-only\n");
    return true;
}
#endif /* Pico */
