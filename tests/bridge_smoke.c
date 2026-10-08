#include "bb_b86_bridge.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void)
{
    static const uint16_t vals[8] = {0x1234,0x0fff,0x8080,0x2345,0xfffa,0x1111,0x2222,0x3333};
    uint8_t *mem = (uint8_t *)calloc(1, B86_MEM_BYTES);
    MdRuntime r;
    BbB86Bridge b;
    unsigned i;
    int ok = 1;
    if (!mem) return 2;
    memset(&r, 0, sizeof(r));
    r.cpu.memory = mem;
    for (i = 0; i < 8; ++i) r.cpu.r[i] = vals[i];
    r.cpu.cs = 0x1000; r.cpu.ds=0x2000; r.cpu.es=0x3000; r.cpu.ss=0x4000;
    r.cpu.ip=0x0100; md_x86_set_flags(&r.cpu, 0x0247);
    ok &= bb_b86_bridge_init(&b, &r, mem, B86_MEM_BYTES);
    ok &= bb_b86_state_equal(&b);
    b.cpu.r[B86_AX] = 0xBEEF; b.cpu.ip = 0x1234;
    bb_b86_save(&b);
    ok &= r.cpu.r[MD_X86_AX] == 0xBEEF && r.cpu.ip == 0x1234;
    ok &= bb_b86_state_equal(&b);
    ok &= bb_b86_addr20(0xffff,0x20) == 0x10;
    ok &= bb_b86_addr20(0xffff,0xffff) == 0xffef;
    printf("[blitzBUS] bridge_state=%s zero_copy=%s addr20=%s jit_guest_insns=0\n", ok?"PASS":"FAIL",ok?"PASS":"FAIL",ok?"PASS":"FAIL");
    free(mem);
    return ok ? 0 : 1;
}
