#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Emulate the Pico SDK's named uninitialized PSRAM section in host tests. */
#define __uninitialized_psram(name) __attribute__((section(".test_psram." name)))
typedef struct { struct { uint8_t *memory; } cpu; } MdRuntime;
static unsigned bb_video_seen;
static int enabled = 1;
static uint64_t test_now;
static bool bb_vga_active(void){return false;}
static bool bb_sd_dos622_active(void){return enabled != 0;}
static uint64_t bb_now_us(void){return test_now;}
#define PICO_ON_DEVICE 1
#include "bb_dos622_textio.inc"
int main(void) {
    MdRuntime rt = {0};
    rt.cpu.memory = (uint8_t *)calloc(1, 1100000);
    if (!rt.cpu.memory) return 1;
    /* Pretend PSRAM contains old state left over from an earlier boot. */
    memset(&bb622_textio_state, 0xA5, sizeof bb622_textio_state);
    bb622_textio_reset();
    for (unsigned i = 0; i < sizeof bb622_textio_state; ++i)
        if (((const uint8_t *)&bb622_textio_state)[i] != 0) return 2;
    for (int i = 0; i < 80; i++) rt.cpu.memory[0xB8000 + i * 2] = ' ';
    const char *p = "A:\\>";
    for (unsigned i = 0; p[i]; i++) rt.cpu.memory[0xB8000 + i*2] = (uint8_t)p[i];
    test_now = 1000000;
    bb622_textio_mirror(&rt);
    if (!bb622_textio_state.row_hash[0] || bb622_textio_state.row_visible[0] != 1u) return 3;
    uint32_t old = bb622_textio_state.row_hash[0];
    rt.cpu.memory[0xB8000] = 'C';
    test_now += 1000;
    bb622_textio_mirror(&rt);
    if (bb622_textio_state.row_hash[0] != old) return 4;
    test_now += 250000;
    bb622_textio_mirror(&rt);
    if (bb622_textio_state.row_hash[0] == old) return 5;
    old = bb622_textio_state.row_hash[0];
    enabled = 0; test_now += 250000;
    rt.cpu.memory[0xB8000] = 'D';
    bb622_textio_mirror(&rt);
    if (bb622_textio_state.row_hash[0] != old) return 6;
    bb622_textio_reset();
    if (bb622_textio_state.row_hash[0] || bb622_textio_state.announced) return 7;
    free(rt.cpu.memory);
    puts("TEXTIO PSRAM C TEST PASS");
    return 0;
}
