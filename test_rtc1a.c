#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define BB622_FLASH __attribute__((noinline))
#define MD_X86_AX 0
#define MD_X86_CX 1
#define MD_X86_DX 2
#define MD_X86_FLAG_CF 0x0001u
typedef struct MdX86 {uint16_t r[8],flags;uint8_t bda_midnight;} MdX86;
typedef struct MdRuntime {MdX86 cpu;} MdRuntime;
static uint64_t mock_us;
static uint64_t time_us_64(void) {return mock_us;}
static uint16_t md_x86_flags(MdX86 *c) {return c->flags;}
static void md_x86_set_flags(MdX86 *c,uint16_t f) {c->flags=f;}
static void md_x86_write8(MdX86 *c,uint16_t seg,uint16_t offset,uint8_t val)
{assert(seg==0x40u&&offset==0x70u);c->bda_midnight=val;}
#include "bb_dos622_rtc1a.inc"
static void call(MdRuntime *r,uint8_t ah) {r->cpu.r[MD_X86_AX]=(uint16_t)ah<<8;assert(bb622_rtc_int1a(r));}
static void date(MdRuntime *r,uint16_t y,uint8_t month,uint8_t day)
{
    r->cpu.r[MD_X86_CX] = (uint16_t)(((unsigned)bb622_to_bcd(y/100u)<<8) | bb622_to_bcd(y%100u));
    r->cpu.r[MD_X86_DX] = (uint16_t)(((unsigned)bb622_to_bcd(month)<<8) | bb622_to_bcd(day));
    call(r,5);
    assert(!(r->cpu.flags & MD_X86_FLAG_CF));
}
static void settime(MdRuntime *r,uint8_t h,uint8_t m,uint8_t s)
{
    r->cpu.r[MD_X86_CX] = (uint16_t)(((unsigned)bb622_to_bcd(h)<<8) | bb622_to_bcd(m));
    r->cpu.r[MD_X86_DX] = (uint16_t)((unsigned)bb622_to_bcd(s)<<8);
    call(r,3);
    assert(!(r->cpu.flags & MD_X86_FLAG_CF));
}
int main(void)
{
    MdRuntime r={0};
    mock_us=1500000ull;
    call(&r,2);assert(!(r.cpu.flags&MD_X86_FLAG_CF));
    assert(bb622_from_bcd((uint8_t)(r.cpu.r[MD_X86_CX]>>8))<24);
    assert(bb622_from_bcd((uint8_t)(r.cpu.r[MD_X86_CX]))<60);
    call(&r,4);assert(!(r.cpu.flags&MD_X86_FLAG_CF));
    assert(r.cpu.bda_midnight==0);
    date(&r,2024,2,28);settime(&r,23,59,58);
    mock_us+=3000000ull;
    call(&r,2);
    assert(r.cpu.r[MD_X86_CX]==0x0000u && r.cpu.r[MD_X86_DX]==0x0100u);
    call(&r,4);
    assert(r.cpu.r[MD_X86_CX]==0x2024u && r.cpu.r[MD_X86_DX]==0x0229u);
    date(&r,2025,12,31);settime(&r,23,59,59);
    mock_us+=2000000ull;
    call(&r,4);
    assert(r.cpu.r[MD_X86_CX]==0x2026u && r.cpu.r[MD_X86_DX]==0x0101u);
    r.cpu.r[MD_X86_CX]=0x2025u;r.cpu.r[MD_X86_DX]=0x0230u;
    call(&r,5);assert(r.cpu.flags&MD_X86_FLAG_CF); /* invalid Feb 30 */
    r.cpu.r[MD_X86_CX]=0x2461u;r.cpu.r[MD_X86_DX]=0x0000u;
    call(&r,3);assert(r.cpu.flags&MD_X86_FLAG_CF); /* invalid hours/minutes */
    call(&r,6);assert(r.cpu.flags&MD_X86_FLAG_CF); /* alarm absent */
    call(&r,7);assert(!(r.cpu.flags&MD_X86_FLAG_CF));
    puts("RTC BCD READ/WRITE + midnight/leap/year + invalid values PASS");
    return 0;
}
