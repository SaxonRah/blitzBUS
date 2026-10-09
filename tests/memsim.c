#include <stdint.h>
#include <stdio.h>
/* RP2350-like XIP cache model: 16 KiB, 2-way, 8-byte lines, LRU, write-allocate */
static uint32_t tag[1024][2]; static uint8_t lru[1024], valid[1024][2];
uint64_t ms_acc[8], ms_miss[8]; int ms_on;
static int region(uint32_t a) {
    if (a >= 0xA0000 && a < 0xB0000) return 1;          /* VGA */
    if (a >= 0x222D0 && a < 0x31CD0) return 2;          /* back buffer (ES=222D) */
    if (a >= 0x416D0 && a < 0x516D0) return 3;          /* SS=416D segment */
    if (a >= 0x14DB0 && a < 0x24DB0) return 4;          /* DS=14DB segment */
    return 5;
}
void b86_memtrace(uint32_t a, int write)
{
    if (!ms_on) return;
    uint32_t line = a >> 3, set = line & 1023, t = line >> 10;
    int r = region(a);
    ms_acc[r]++; ms_acc[6 + write]++;
    for (int w = 0; w < 2; ++w) if (valid[set][w] && tag[set][w] == t) { lru[set] = (uint8_t)(1 - w); return; }
    ms_miss[r]++; ms_miss[6 + write]++;
    int v = lru[set]; tag[set][v] = t; valid[set][v] = 1; lru[set] = (uint8_t)(1 - v);
}
