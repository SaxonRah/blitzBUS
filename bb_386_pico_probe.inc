/* BB_386_PM0_V1: opt-in boot-time RP2350 386 interpreter/PM0 smoke.
 * Runs BEFORE the DOS/JIT CPU is configured and the 232 KiB cache created.
 * Private B86Cpu + 1024-byte backup are in PSRAM, not 512 KiB SRAM.
 * Uses guest HMA [0x100000,0x1003ff] only after saving all its bytes.
 */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#include "b86_pm0.h"
static B86Cpu __uninitialized_psram("bb386_probe_cpu") bb386_test_cpu;
static uint8_t __uninitialized_psram("bb386_probe_save") bb386_test_save[1024];
#define BB386_TEST_FLASH __attribute__((noinline,cold,section(".text.bb386_flash")))

static BB386_TEST_FLASH void bb386_test_program(uint8_t *mem, const uint8_t *p, unsigned n)
{
    memset(mem + 0x100000u, 0, 32);
    memcpy(mem + 0x100000u, p, n);
    bb386_test_cpu.ip = 0x100;
}

static BB386_TEST_FLASH void bb386_test_setup(uint8_t *mem)
{
    b86_init(&bb386_test_cpu, mem);
    bb386_test_cpu.model = B86_CPU_386;
    b86_set_seg(&bb386_test_cpu, B86_CS, 0xFFF0);
    b86_set_seg(&bb386_test_cpu, B86_DS, 0xFFE0);
    b86_set_seg(&bb386_test_cpu, B86_SS, 0xFFE0);
    bb386_test_cpu.r[B86_SP] = 0x12340500u;
    bb386_test_cpu.ip = 0x100;
}

static BB386_TEST_FLASH void bb386_test_put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static BB386_TEST_FLASH int bb386_test_run(uint8_t *guest)
{
    unsigned ok = 0, bad = 0;
    B86Cpu *c = &bb386_test_cpu;
    B86PM0Desc desc;
    /* Snapshot every byte touched, including 32-bit SS stack writes. */
    memcpy(bb386_test_save, guest + 0x100000u, sizeof bb386_test_save);
    do {
        static const uint8_t movadd[] = {
            0x66,0xB8,0x78,0x56,0x34,0x12, /* MOV EAX,12345678 */
            0xB8,0xCD,0xAB,                 /* MOV AX,ABCD */
            0x66,0x05,0x01,0,0,0           /* ADD EAX,1 */
        };
        static const uint8_t sib[] = {
            0x67,0x66,0x8B,0x04,0x8D,0x00,0x03,0x00,0x00
        }; /* MOV EAX,[ECX*4+0300h] */
        static const uint8_t fs[] = {
            0x8E,0xE0,                     /* MOV FS,AX */
            0x64,0x66,0x8B,0x06,0x20,0x03  /* MOV EAX,FS:[0320] */
        };
        static const uint8_t callret[] = {
            0x66,0xE8,0x01,0,0,0,0x90,0x66,0xC3
        };
        static const uint8_t flat32[8] = {
            0xFF,0xFF,0,0,0,0x9A,0xCF,0
        };
        memset(guest + 0x100000u, 0, sizeof bb386_test_save);
        bb386_test_setup(guest);
        bb386_test_program(guest,movadd,sizeof movadd);
        if (b86_step(c) != B86_OK || c->r[B86_AX] != 0x12345678u) { bad=1;break; }++ok;
        if (b86_step(c) != B86_OK || c->r[B86_AX] != 0x1234ABCDu) { bad=2;break; }++ok;
        if (b86_step(c) != B86_OK || c->r[B86_AX] != 0x1234ABCEu) { bad=3;break; }++ok;

        bb386_test_setup(guest);
        bb386_test_program(guest,sib,sizeof sib);
        c->r[B86_CX]=4;
        bb386_test_put32(guest+0x100110u,0x76543210u);
        if (b86_step(c) != B86_OK || c->r[B86_AX] != 0x76543210u) { bad=4;break; }++ok;

        bb386_test_setup(guest);
        bb386_test_program(guest,fs,sizeof fs);
        c->r[B86_AX]=0xFFE0u;
        bb386_test_put32(guest+0x100120u,0xC0DEC0DEu);
        if (b86_step(c) != B86_OK || c->seg386[0] != 0xFFE0u) { bad=5;break; }++ok;
        if (b86_step(c) != B86_OK || c->r[B86_AX] != 0xC0DEC0DEu) { bad=6;break; }++ok;

        bb386_test_setup(guest);
        bb386_test_program(guest,callret,sizeof callret);
        if (b86_step(c) != B86_OK || c->ip != 0x107u ||
            c->r[B86_SP] != 0x123404FCu) { bad=7;break; }++ok;
        if (b86_step(c) != B86_OK || c->ip != 0x106u ||
            c->r[B86_SP] != 0x12340500u) { bad=8;break; }++ok;

        c->gdt_base=0x100200u;
        c->gdt_limit=0x17u;
        memcpy(guest+0x100208u,flat32,8);
        if (b86_pm0_lookup_gdt(c,8,&desc) != B86_PM0_OK ||
            desc.limit != 0xFFFFFFFFu || !desc.default32 ||
            !desc.executable) { bad=9;break; }++ok;
        if (b86_pm0_lookup_gdt(c,0x18,&desc) != B86_PM0_TABLE_LIMIT) { bad=10;break; }++ok;
    } while (0);
    /* ALWAYS restore the guest's HMA and leave the active 286 CPU untouched. */
    memcpy(guest + 0x100000u, bb386_test_save, sizeof bb386_test_save);
    if (bad) printf("[bb-386-pico] FAIL test=%u passed=%u/10 (286 boot continues)\n",bad,ok);
    else printf("[bb-386-pico] PASS 10/10 386 interpreter+GDT, guest HMA restored\n");
    return bad ? -1 : 0;
}
#endif
