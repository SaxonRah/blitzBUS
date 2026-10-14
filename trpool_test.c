#include <stdint.h>
#include <string.h>
#ifndef BB_TR_PAGES
#define BB_TR_PAGES 24u
#endif
#define MD_X86_CODE_PAGE_SIZE 4096u
#define __uninitialized_psram(name) __attribute__((section(".psram_test")))
static uint8_t *trbits[256];
static unsigned trpool_used;
/* BB_DOS622_HEAP_RESCUE_V1: reclaim core SRAM for the JIT calloc heap.
 * Keep the first 16 translated-page bitmaps in fast SRAM (DOS2 peaked at 15).
 * The remaining BB_TR_PAGES - 16 entries are in PSRAM; each is zeroed on use.
 * No changes to BB_CODE_BYTES, JIT entry code, or the CPU interpreter. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#define BB_TR_HOT_PAGES ((BB_TR_PAGES) > 16u ? 16u : (BB_TR_PAGES))
static uint8_t trpool[BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#if BB_TR_PAGES > BB_TR_HOT_PAGES
static uint8_t __uninitialized_psram("bb_trpool_cold")
    trpool_cold[BB_TR_PAGES - BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
#else
static uint8_t trpool[BB_TR_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
void track(unsigned p) {
 if (trpool_used < BB_TR_PAGES) {
                #if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && (BB_TR_PAGES > 16u)
                trbits[p] = trpool_used < 16u ? trpool[trpool_used]
                            : trpool_cold[trpool_used - 16u];
#else
                trbits[p] = trpool[trpool_used];
#endif
                ++trpool_used;
                memset(trbits[p], 0, MD_X86_CODE_PAGE_SIZE / 8u);
 }
}
int main(void) { for(unsigned i=0;i<BB_TR_PAGES;i++)track(i);return trpool_used != BB_TR_PAGES; }
