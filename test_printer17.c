/* Standalone correctness check for INT17 without Pico SDK headers. */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define BB622_FLASH
#define MD_X86_AX 0
#define MD_X86_DX 2
typedef struct MdX86 { uint16_t r[8],flags; } MdX86;
typedef struct MdRuntime { MdX86 cpu; } MdRuntime;
#include "bb_dos622_printer17.inc"
int main(void) {
    MdRuntime rt; memset(&rt,0,sizeof rt);
    rt.cpu.flags=0x0202;
    rt.cpu.r[MD_X86_AX]=0x0102;
    rt.cpu.r[MD_X86_DX]=2;
    assert(bb622_printer17(&rt));
    assert(rt.cpu.r[MD_X86_AX]==0x0102); /* AH=01 status; AL preserved */
    assert(rt.cpu.r[MD_X86_DX]==2 && rt.cpu.flags==0x0202);
    rt.cpu.r[MD_X86_AX]=0x005a;
    assert(bb622_printer17(&rt));
    assert(rt.cpu.r[MD_X86_AX]==0x015a);
    rt.cpu.r[MD_X86_AX]=0x0200;
    assert(bb622_printer17(&rt));
    assert(rt.cpu.r[MD_X86_AX]==0x0100);
    puts("PASS: BIOS INT17 AH=00/01/02 absent LPT timeout, AL/flags preserved");
    return 0;
}
