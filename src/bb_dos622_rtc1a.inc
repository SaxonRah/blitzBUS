/* BB_DOS622_RTC1A_V1
 * AT-compatible BIOS INT 1Ah CMOS clock support for optional DOS 6.22.
 * AH=02 read BCD hh:mm:ss + DST, AH=03 set time,
 * AH=04 read BCD century/year/month/day, AH=05 set date,
 * AH=06 alarm unsupported (CF=1), AH=07 reset alarm (CF=0).
 * Boot defaults come from firmware __DATE__ and __TIME__ and advance using
 * the Pico monotonic timer. No battery-backed RTC or host clock sync exists.
 * All code in flash; a small mutable clock state in SRAM. No heap allocations.
 */
typedef struct Bb622RtcState {
    uint64_t anchor_us;
    uint32_t sec_of_day;
    uint16_t year;
    uint8_t month, day, dst, started;
} Bb622RtcState;
static Bb622RtcState bb622_rtc_state;
static unsigned bb622_rtc_logs;

static uint8_t BB622_FLASH bb622_to_bcd(unsigned n)
{ return (uint8_t)(((n / 10u) << 4u) | (n % 10u)); }
static int BB622_FLASH bb622_from_bcd(uint8_t n)
{
    if ((n & 15u) > 9u || (n >> 4u) > 9u) return -1;
    return (int)((n >> 4u) * 10u + (n & 15u));
}
static unsigned BB622_FLASH bb622_month_days(unsigned year, unsigned month)
{
    static const uint8_t days[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
    if (month < 1u || month > 12u) return 0;
    if (month == 2u && year % 4u == 0u && (year % 100u != 0u || year % 400u == 0u)) return 29;
    return days[month - 1u];
}
static void BB622_FLASH bb622_rtc_next_day(void)
{
    Bb622RtcState *s = &bb622_rtc_state;
    if (++s->day > bb622_month_days(s->year, s->month)) {
        s->day = 1u;
        if (++s->month > 12u) {
            s->month = 1u;
            ++s->year;
            if (s->year > 2099u) s->year = 1980u;
        }
    }
}
static void BB622_FLASH bb622_rtc_init(void)
{
    Bb622RtcState *s = &bb622_rtc_state;
    if (s->started) return;
    /* The host build date/time is only a seed, not a synchronized RTC. */
    const char *d = __DATE__, *t = __TIME__;
    static const char months[] = "JanFebMarAprMayJunJulAugSepOctNovDec";
    unsigned month = 0u;
    for (unsigned i = 0; i < 12u; ++i)
        if (memcmp(d, months + i*3u, 3u) == 0) { month = i + 1u; break; }
    unsigned day = (unsigned)(d[4] == ' ' ? 0 : d[4] - '0')*10u + (unsigned)(d[5] - '0');
    unsigned year = (unsigned)(d[7]-'0')*1000u + (unsigned)(d[8]-'0')*100u +
                    (unsigned)(d[9]-'0')*10u + (unsigned)(d[10]-'0');
    if (year < 1980u || year > 2099u || !month || day < 1u || day > bb622_month_days(year, month)) {
        year = 2026u; month = 1u; day = 1u;
    }
    s->year = (uint16_t)year; s->month = (uint8_t)month; s->day = (uint8_t)day;
    s->sec_of_day = ((unsigned)(t[0]-'0')*10u + (unsigned)(t[1]-'0'))*3600u +
                    ((unsigned)(t[3]-'0')*10u + (unsigned)(t[4]-'0'))*60u +
                    (unsigned)(t[6]-'0')*10u + (unsigned)(t[7]-'0');
    if (s->sec_of_day >= 86400u) s->sec_of_day = 12u*3600u;
    s->anchor_us = time_us_64();
    s->dst = 0u;
    s->started = 1u;
    printf("[bb622-rtc1a] emulated RTC seeded from build date %04u-%02u-%02u %02u:%02u:%02u (not synchronized)\n",
           year, month, day, (unsigned)(s->sec_of_day / 3600u),
           (unsigned)(s->sec_of_day / 60u) % 60u, (unsigned)(s->sec_of_day % 60u));
    fflush(stdout);
}
static void BB622_FLASH bb622_rtc_advance(void)
{
    Bb622RtcState *s = &bb622_rtc_state;
    bb622_rtc_init();
    const uint64_t now = time_us_64();
    if (now < s->anchor_us) { s->anchor_us = now; return; }
    const uint64_t elapsed = (now - s->anchor_us) / 1000000ull;
    if (!elapsed) return;
    s->anchor_us += elapsed * 1000000ull;
    const uint64_t total = (uint64_t)s->sec_of_day + elapsed;
    s->sec_of_day = (uint32_t)(total % 86400ull);
    uint64_t day_delta = total / 86400ull;
    while (day_delta--) bb622_rtc_next_day();
}
static void BB622_FLASH bb622_rtc_result(MdX86 *cpu, bool error)
{
    uint16_t f = md_x86_flags(cpu);
    if (error) f |= MD_X86_FLAG_CF;
    else f &= (uint16_t)~MD_X86_FLAG_CF;
    md_x86_set_flags(cpu, f);
}
static bool BB622_FLASH bb622_rtc_int1a(MdRuntime *rt)
{
    MdX86 *c = &rt->cpu;
    Bb622RtcState *s = &bb622_rtc_state;
    const uint8_t fn = (uint8_t)(c->r[MD_X86_AX] >> 8);
    bb622_rtc_advance();
    if (fn == 0x02u) {
        unsigned hh=s->sec_of_day/3600u, mm=(s->sec_of_day/60u)%60u, ss=s->sec_of_day%60u;
        c->r[MD_X86_CX] = (uint16_t)((uint16_t)bb622_to_bcd(hh)<<8u | bb622_to_bcd(mm));
        c->r[MD_X86_DX] = (uint16_t)((uint16_t)bb622_to_bcd(ss)<<8u | s->dst);
        bb622_rtc_result(c, false);
    } else if (fn == 0x04u) {
        c->r[MD_X86_CX] = (uint16_t)((uint16_t)bb622_to_bcd(s->year/100u)<<8u | bb622_to_bcd(s->year%100u));
        c->r[MD_X86_DX] = (uint16_t)((uint16_t)bb622_to_bcd(s->month)<<8u | bb622_to_bcd(s->day));
        bb622_rtc_result(c, false);
        md_x86_write8(c, 0x0040u, 0x0070u, 0u); /* BDA midnight rollover acknowledgement */
    } else if (fn == 0x03u) {
        const int hh=bb622_from_bcd((uint8_t)(c->r[MD_X86_CX]>>8u));
        const int mm=bb622_from_bcd((uint8_t)c->r[MD_X86_CX]);
        const int ss=bb622_from_bcd((uint8_t)(c->r[MD_X86_DX]>>8u));
        if (hh<0 || hh>23 || mm<0 || mm>59 || ss<0 || ss>59) bb622_rtc_result(c, true);
        else {
            s->sec_of_day=(uint32_t)(hh*3600 + mm*60 + ss);
            s->dst=(uint8_t)(c->r[MD_X86_DX] & 1u);
            s->anchor_us=time_us_64();
            bb622_rtc_result(c, false);
        }
    } else if (fn == 0x05u) {
        const int cc=bb622_from_bcd((uint8_t)(c->r[MD_X86_CX]>>8u));
        const int yy=bb622_from_bcd((uint8_t)c->r[MD_X86_CX]);
        const int month=bb622_from_bcd((uint8_t)(c->r[MD_X86_DX]>>8u));
        const int day=bb622_from_bcd((uint8_t)c->r[MD_X86_DX]);
        const int year=cc*100+yy;
        if (cc<0 || yy<0 || year<1980 || year>2099 || month<1 || month>12 ||
            day<1 || day>(int)bb622_month_days((unsigned)year,(unsigned)month))
            bb622_rtc_result(c, true);
        else {s->year=(uint16_t)year; s->month=(uint8_t)month; s->day=(uint8_t)day; bb622_rtc_result(c,false);}
    } else if (fn == 0x06u) {
        bb622_rtc_result(c, true); /* No alarm hardware */
    } else if (fn == 0x07u) {
        bb622_rtc_result(c, false); /* No alarm armed */
    }
    if (++bb622_rtc_logs <= 20u) {
        printf("[bb622-rtc1a] fn=%02X CX=%04X DX=%04X CF=%u\n",
               (unsigned)fn,(unsigned)c->r[MD_X86_CX],(unsigned)c->r[MD_X86_DX],
               (unsigned)((md_x86_flags(c)&MD_X86_FLAG_CF)!=0));
        fflush(stdout);
    }
    return true;
}
