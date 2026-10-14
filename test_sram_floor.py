from pathlib import Path
import sys, subprocess, tempfile
sys.path.insert(0,str(Path(__file__).parent))
from bb_dos622_sram_floor_v1 import transform
src='''#include <stdint.h>
#include <string.h>
#define MD_X86_CODE_PAGE_SIZE 4096u
#ifndef BB_TR_PAGES
#define BB_TR_PAGES 24u
#endif
#define __uninitialized_psram(name) __attribute__((section(".psram")))
static uint8_t *trbits[256];
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
static unsigned trpool_used;
void touch(unsigned p) {
   if (trpool_used < BB_TR_PAGES) {
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && (BB_TR_PAGES > 16u)
                trbits[p] = trpool_used < 16u ? trpool[trpool_used]
                            : trpool_cold[trpool_used - 16u];
#else
                trbits[p] = trpool[trpool_used];
#endif
                ++trpool_used;
                memset(trbits[p], 0, MD_X86_CODE_PAGE_SIZE/8u);
   }
}
int main(void) {
  for (unsigned i=0;i<(BB_TR_PAGES<24u?BB_TR_PAGES:24u);++i) touch(i);
  for (unsigned i=0;i<(BB_TR_PAGES<24u?BB_TR_PAGES:24u);++i) {
    if (!trbits[i]) return 1;
    trbits[i][511]=(uint8_t)i;
  }
  for (unsigned i=0;i<(BB_TR_PAGES<24u?BB_TR_PAGES:24u);++i) if(trbits[i][511]!=i) return 2;
  return 0;
}
'''
data=transform(src.encode())
for compiler in ('gcc','clang'):
    for pico in (0,1):
        for pages in (8,16,24,32):
            with tempfile.TemporaryDirectory(prefix='floor_c_') as t:
                c=Path(t)/'test.c';ex=Path(t)/'test';c.write_bytes(data)
                cmd=[compiler,'-std=c11','-Wall','-Wextra','-Werror','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',f'-DPICO_ON_DEVICE={pico}',f'-DBB_TR_PAGES={pages}',str(c),'-o',str(ex)]
                p=subprocess.run(cmd,capture_output=True,text=True)
                if p.returncode:
                    print(cmd);print(p.stderr);raise AssertionError(f'{compiler} Pico={pico} pages={pages} compile failed')
                r=subprocess.run([str(ex)],capture_output=True,text=True)
                if r.returncode: print(r.stderr);raise AssertionError(f'{compiler} Pico={pico} pages={pages} run failed')
                print(f'{compiler} PICO={pico} PAGES={pages}: compile+sanitizers PASS')
# inspect target .bss vs PSRAM symbol sizes
with tempfile.TemporaryDirectory(prefix='floor_obj_') as t:
    c=Path(t)/'test.c';o=Path(t)/'test.o';c.write_bytes(data)
    subprocess.run(['gcc','-std=c11','-O1','-DPICO_ON_DEVICE=1','-c',str(c),'-o',str(o)],check=True)
    s=subprocess.check_output(['nm','-S','--size-sort',str(o)],text=True)
    print('SYMBOLS:', '\n'.join(x for x in s.splitlines() if 'trpool' in x))
print('FULL COMPILE/EXEC TEST PASS')
