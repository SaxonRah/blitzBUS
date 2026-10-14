#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
typedef struct MdRuntime { unsigned marker; } MdRuntime;
static MdRuntime *R;
static int delivered;
static int mounted;
static int __attribute__((unused)) bb_sd_dos622_active(void) { return mounted; }
static void bb_irq36_dispatch(MdRuntime *rt, unsigned now) { (void)rt; (void)now; delivered++; }
static unsigned bb_now_us(void) { return 1; }
static void dos622_boot(void) {
#ifndef BB622_IRQ0_AB_DISABLE
#define BB622_IRQ0_AB_DISABLE 1
#endif
#if BB622_IRQ0_AB_DISABLE
    printf("[bb622-irq0-ab] IRQ0 delivery SUPPRESSED for DOS622 ONLY (diagnostic, not final fix)\n");
#else
    printf("[bb622-irq0-ab] IRQ0 delivery ENABLED for DOS622 (control)\n");
#endif
}
static void tick(MdRuntime *rt) {
    if (rt == R) {
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
        if (!bb_sd_dos622_active()) bb_irq36_dispatch(rt, bb_now_us());
#else
        bb_irq36_dispatch(rt, bb_now_us());
#endif
    }
}
int main(void) {
    MdRuntime r={0}; R=&r; dos622_boot();
    mounted=0; tick(&r);
    mounted=1; tick(&r);
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
    if(delivered!=1)return 2;
#else
    if(delivered!=2)return 3;
#endif
    printf("AB TEST PASS delivered=%d\n",delivered);
    return 0;
}
