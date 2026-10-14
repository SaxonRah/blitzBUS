#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define BB622_FLASH
#define MD_X86_AX 0
#define MD_X86_CX 1
#define MD_X86_DX 2
#define MD_X86_BX 3
#define MD_STOP_FAULT 4
#define MD_STOP_NONE 0
typedef struct MdX86 {
    uint16_t r[8], cs, ip, flags;
    uint8_t mem[256];
} MdX86;
typedef struct MdRuntime { MdX86 cpu; int stop_reason; uint32_t fault_linear; } MdRuntime;
static uint16_t md_x86_read16(MdX86 *c, uint16_t seg, uint16_t off) {
    assert(!seg && (size_t)off + 1u < sizeof c->mem);
    return (uint16_t)((uint16_t)c->mem[off] | (uint16_t)c->mem[off+1] << 8);
}
#include "bb_dos622_serial14.inc"
int main(void) {
    MdRuntime rt; memset(&rt,0,sizeof rt);
    rt.cpu.r[MD_X86_AX]=0x00A3; rt.cpu.r[MD_X86_DX]=3;
    rt.cpu.flags=0x0202;
    assert(bb622_serial14(&rt));
    assert(rt.cpu.r[MD_X86_AX]==0x8000 && rt.cpu.r[MD_X86_DX]==3);
    assert(rt.cpu.flags==0x0202 && rt.stop_reason==MD_STOP_NONE);
    rt.cpu.r[MD_X86_AX]=0x0155;
    assert(bb622_serial14(&rt)); assert(rt.cpu.r[MD_X86_AX]==0x8055);
    for(unsigned i=2; i<12; ++i) {
        rt.cpu.r[MD_X86_AX] = (uint16_t)((i<<8)|0xA3u);
        assert(bb622_serial14(&rt));
        assert(rt.cpu.r[MD_X86_AX]==0x8000);
    }
    rt.cpu.cs=0x70; rt.cpu.ip=0x22ae;
    rt.cpu.r[MD_X86_AX]=0x00A3;
    assert(!bb622_null_firmware_vector(&rt,0x21));
    assert(rt.stop_reason==MD_STOP_NONE);
    rt.cpu.mem[0x14*4] = 0x20;
    assert(!bb622_null_firmware_vector(&rt,0x14));
    rt.cpu.mem[0x14*4] = 0;
    assert(bb622_null_firmware_vector(&rt,0x14));
    assert(rt.stop_reason==MD_STOP_FAULT && rt.fault_linear==0x29ae);
    puts("PASS: absent serial INT14, flags preservation, null-vector guard, DOS INT21 bypass");
    return 0;
}
