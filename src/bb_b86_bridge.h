#ifndef BB_B86_BRIDGE_H
#define BB_B86_BRIDGE_H
#include <stdint.h>
#include "b86.h"
#include "microdos/runtime.h"
#ifdef __cplusplus
extern "C" {
#endif
/* This bridge does not allocate memory or enable the JIT. */
typedef struct BbB86Bridge {
    B86Cpu cpu;
    MdRuntime *runtime;
    uint64_t committed;
    uint64_t denied;
    uint64_t interrupts;
    uint64_t jit_instructions;
    int ready;
} BbB86Bridge;
/* Called with an existing >= B86_MEM_BYTES guest allocation. The first 1MiB
 * is shared with microDOS. Guarded by readiness, never claim JIT execution. */
int bb_b86_bridge_init(BbB86Bridge *b, MdRuntime *rt, uint8_t *memory, size_t memory_size);
void bb_b86_load(BbB86Bridge *b);
void bb_b86_save(BbB86Bridge *b);
/* Returns nonzero iff CPU register/segment/IP/defined flag state matches. */
int bb_b86_state_equal(BbB86Bridge *b);
/* Pure 20-bit address conversion guard. Not a replacement for the JIT's
 * A20-on, linear segment-pointer memory addressing. */
uint32_t bb_b86_addr20(uint16_t segment, uint16_t offset);
#ifdef __cplusplus
}
#endif
#endif
