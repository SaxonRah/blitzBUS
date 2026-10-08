/* blitzBUS v0.6: real RP2350 Thumb-2 JIT execution gate.
 * This is deliberately separate from working DOS/LCD firmware.
 * No synthetic JIT counter: only b86_jit_stats() decides PASS.
 */
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/psram.h"
#include "hardware/clocks.h"
#include "b86.h"

static uint8_t __uninitialized_psram("bb_guest") guest[B86_MEM_BYTES];
static uint8_t code[64u * 1024u] __attribute__((aligned(16)));
static B86Cpu cpu;
static unsigned interrupts_seen;
static const uint8_t program[] = {
    0xB8,0x01,0x00,             /* MOV AX,1 */
    0x05,0x02,0x00,             /* ADD AX,2 */
    0xCD,0x60,                  /* INT 60h -> our test service */
    0xA3,0x00,0x02,             /* MOV [0200h],AX */
    0xF4                        /* HLT */
};
static int on_interrupt(B86Cpu *c, uint8_t vector) {
    if (vector != 0x60) return 0;
    ++interrupts_seen;
    c->r[B86_AX] = (c->r[B86_AX] + 4u) & 0xffffu;
    return 1;
}
int main(void) {
    struct B86Jit *jit;
    const B86JitStats *stats;
    int rc, pass;
    stdio_init_all();
    while (!stdio_usb_connected()) sleep_ms(20);
    sleep_ms(200);
    printf("[blitzBUS] jit_probe=START target=RP2350 backend=blitz86-thumb2\n");
    printf("[blitzBUS] guest_bytes=%lu psram_available=%d\n",
           (unsigned long)sizeof(guest), psram_is_available() ? 1 : 0);
    if (!psram_is_available() || psram_get_size() < sizeof(guest)) {
        printf("[b86-jit] COMPLETE result=FAIL reason=psram\n");
        goto finish;
    }
    memset(guest,0,sizeof(guest));
    memcpy(guest + 0x10100u,program,sizeof(program));
    b86_init(&cpu, guest);
    b86_set_seg(&cpu,B86_CS,0x1000u);
    b86_set_seg(&cpu,B86_DS,0x1000u);
    b86_set_seg(&cpu,B86_ES,0x1000u);
    b86_set_seg(&cpu,B86_SS,0x1000u);
    cpu.ip = 0x100u;
    cpu.r[B86_SP] = 0xFFFEu;
    cpu.int_hook = on_interrupt;
    jit = b86_jit_create(&cpu,code,sizeof(code));
    if (!jit) {
        printf("[b86-jit] COMPLETE result=FAIL reason=jit-allocation\n");
        goto finish;
    }
    /* A deliberate single-step JIT gate: avoid fast chains until DOS adapter
     * has proved 20-bit wrap, canonical memory stores, and interrupt parity. */
    b86_jit_set_single_step(jit,1);
    rc = b86_jit_run(&cpu,64u);
    stats = b86_jit_stats(jit);
    pass = rc == B86_HALT && (cpu.r[B86_AX] & 0xFFFFu) == 7u &&
           guest[0x10200u] == 7u && guest[0x10201u] == 0u &&
           interrupts_seen == 1u && stats && stats->guest_insns > 0u &&
           stats->blocks > 0u;
    printf("[b86-jit] backend=blitz86-thumb2 retired=%llu blocks=%llu dispatches=%llu interrupt60=%u ax=%04lX stored=%02X%02X rc=%d\n",
           (unsigned long long)(stats ? stats->guest_insns : 0),
           (unsigned long long)(stats ? stats->blocks : 0),
           (unsigned long long)(stats ? stats->dispatches : 0),
           interrupts_seen,(unsigned long)(cpu.r[B86_AX]&0xffffu),
           guest[0x10201u],guest[0x10200u],rc);
    printf("[b86-jit] COMPLETE result=%s\n", pass ? "PASS":"FAIL");
    b86_jit_destroy(jit);
finish:
    stdio_flush();
    for (;;) sleep_ms(1000);
}
