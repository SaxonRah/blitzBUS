/* BB_DOS622_STALL_WATCH_V1
 * Temporary, opt-in MS-DOS 6.22 boot progress watchdog.
 * No CPU/cache/timing semantics are changed. Diagnostics are disabled for DOS 2.
 */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
extern bool bb_sd_dos622_active(void);
static uint32_t bb622_watch_int13_calls, bb622_watch_other_calls;
static uint32_t bb622_watch_ivt_calls, bb622_watch_slices;
static uint64_t bb622_watch_next_us;
static uint64_t bb622_watch_last_retired;

static void __attribute__((noinline,section(".text.bb622")))
bb622_watch_bios(MdRuntime *rt, uint8_t vector)
{
    if (!bb_sd_dos622_active()) return;
    const uint32_t n = vector == 0x13u ? ++bb622_watch_int13_calls : ++bb622_watch_other_calls;
    /* First requests are useful; afterward sample powers of two only. */
    if (n <= 48u || (n & (n - 1u)) == 0u) {
        MdX86 *c = &rt->cpu;
        printf("[bb622-irq] vec=%02X #%lu ax=%04X bx=%04X cx=%04X dx=%04X es=%04X:%04X at=%04X:%04X\n",
               (unsigned)vector, (unsigned long)n, (unsigned)c->r[MD_X86_AX],
               (unsigned)c->r[MD_X86_BX], (unsigned)c->r[MD_X86_CX],
               (unsigned)c->r[MD_X86_DX], (unsigned)c->es,
               (unsigned)c->r[MD_X86_BX], (unsigned)c->cs, (unsigned)c->ip);
        fflush(stdout);
    }
}

static void __attribute__((noinline,section(".text.bb622")))
bb622_watch_ivt(MdRuntime *rt, uint8_t vector)
{
    if (!bb_sd_dos622_active()) return;
    ++bb622_watch_ivt_calls;
    if (bb622_watch_ivt_calls <= 24u || (bb622_watch_ivt_calls & (bb622_watch_ivt_calls - 1u)) == 0u) {
        MdX86 *c = &rt->cpu;
        const unsigned p = (unsigned)vector * 4u;
        const uint8_t *m = c->memory;
        printf("[bb622-ivt] vec=%02X #%lu target=%04X:%04X caller=%04X:%04X (normal when DOS owns vector)\n",
               (unsigned)vector, (unsigned long)bb622_watch_ivt_calls,
               (unsigned)(m[p + 2u] | (m[p + 3u] << 8)),
               (unsigned)(m[p] | (m[p + 1u] << 8)),
               (unsigned)c->cs, (unsigned)c->ip);
        fflush(stdout);
    }
}

static void __attribute__((noinline,section(".text.bb622")))
bb622_watch_slice(MdRuntime *rt)
{
    if (!bb_sd_dos622_active()) return;
    const uint64_t now = bb_now_us();
    if (now < bb622_watch_next_us) return;
    ++bb622_watch_slices;
    bb622_watch_next_us = now + (bb622_watch_slices <= 12u ? 1000000u : 5000000u);
    MdX86 *c = &rt->cpu;
    const uint64_t retired = rt->instructions;
    const uint32_t lin = (((uint32_t)c->cs << 4) + c->ip) & 0xFFFFFu;
    const uint8_t *m = c->memory;
    printf("[bb622-watch] #%lu cs:ip=%04X:%04X phys=%05lX bytes=%02X%02X%02X%02X "
           "ss:sp=%04X:%04X ax=%04X cx=%04X dx=%04X flags=%04X "
           "insns=%llu delta=%llu native=%llu slices=%llu bios13=%lu other=%lu ivt=%lu\n",
           (unsigned long)bb622_watch_slices, (unsigned)c->cs, (unsigned)c->ip,
           (unsigned long)lin, (unsigned)m[lin], (unsigned)m[(lin+1u)&0xFFFFFu],
           (unsigned)m[(lin+2u)&0xFFFFFu], (unsigned)m[(lin+3u)&0xFFFFFu],
           (unsigned)c->ss, (unsigned)c->r[MD_X86_SP],
           (unsigned)c->r[MD_X86_AX], (unsigned)c->r[MD_X86_CX], (unsigned)c->r[MD_X86_DX],
           (unsigned)md_x86_flags(c), (unsigned long long)retired,
           (unsigned long long)(retired - bb622_watch_last_retired),
           (unsigned long long)st.retired, (unsigned long long)st.slices,
           (unsigned long)bb622_watch_int13_calls,
           (unsigned long)bb622_watch_other_calls,
           (unsigned long)bb622_watch_ivt_calls);
    bb622_watch_last_retired = retired;
    fflush(stdout);
}
#else
static inline void bb622_watch_bios(MdRuntime *rt, uint8_t vector) { (void)rt; (void)vector; }
static inline void bb622_watch_ivt(MdRuntime *rt, uint8_t vector) { (void)rt; (void)vector; }
static inline void bb622_watch_slice(MdRuntime *rt) { (void)rt; }
#endif
