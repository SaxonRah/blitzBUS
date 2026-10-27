#ifndef BB622_IRQ0_BURST_H
#define BB622_IRQ0_BURST_H
/* Diagnostic ONLY. 64-IRQ stress with auto-stop; no new PIC/PIT or CPU storage.
 * Pure state machine so it can be unit-tested outside the Pico build.
 * Caller owns all IRQ delivery and remains responsible for exact PIC timing.
 */
#include <stdint.h>

enum { BB622_IRQ_BURST_MAX = 64 };
#define BB622_IRQ_BURST_TOTAL_US 20000000ull
#define BB622_IRQ_BURST_ACK_US   1500000ull
#define BB622_IRQ_BURST_RETRY_US   10000ull
#define BB622_IRQ_BURST_GAP_US     20000ull

typedef struct Bb622IrqBurst {
    uint64_t start_us, last_try_us, delivered_us, observed_eois;
    uint8_t active, waiting, delivered, completed, end_reason;
} Bb622IrqBurst;

enum { BB622_BURST_NONE = 0, BB622_BURST_DELIVER = 1,
       BB622_BURST_FINISHED = 2, BB622_BURST_TIMEOUT = 3 };

static inline void bb622_burst_reset(Bb622IrqBurst *b) {
    Bb622IrqBurst z = {0};
    *b = z;
}
static inline void bb622_burst_arm(Bb622IrqBurst *b, uint64_t now, uint64_t eois) {
    bb622_burst_reset(b);
    b->active = 1;
    b->start_us = now;
    b->observed_eois = eois;
}
/* Only called after the real dispatcher actually accepted IRQ0. */
static inline void bb622_burst_result(Bb622IrqBurst *b, int delivered, uint64_t now,
                                uint64_t eois) {
    if (!b->active) return;
    b->last_try_us = now;
    if (delivered) {
        ++b->delivered;
        b->delivered_us = now;
        b->observed_eois = eois;
        b->waiting = 1;
    }
}
/* flags = current guest FLAGS, isr = existing 8259 ISR, auto_eoi = PIC mode.
 * Do not count a completed interrupt just because EOI was written:
 * IF also needs to be restored (normally by the guest's IRET).
 * Time comparisons use non-wrapping 64-bit monotonic microseconds.
 */
static inline int bb622_burst_poll(Bb622IrqBurst *b, uint64_t now, uint64_t eois,
                             uint8_t isr, uint16_t flags, uint8_t auto_eoi) {
    if (!b->active) return BB622_BURST_NONE;
    if (now < b->start_us || now - b->start_us >= BB622_IRQ_BURST_TOTAL_US) {
        b->active = 0; b->end_reason = BB622_BURST_TIMEOUT;
        return BB622_BURST_TIMEOUT;
    }
    if (b->waiting) {
        const int ack = (auto_eoi || eois > b->observed_eois) && !(isr & 1u);
        if (ack && (flags & 0x0200u)) {
            b->waiting = 0;
            ++b->completed;
            if (b->delivered >= BB622_IRQ_BURST_MAX) {
                b->active = 0; b->end_reason = BB622_BURST_FINISHED;
                return BB622_BURST_FINISHED;
            }
        } else {
            if (now < b->delivered_us || now - b->delivered_us >= BB622_IRQ_BURST_ACK_US) {
                b->active = 0; b->end_reason = BB622_BURST_TIMEOUT;
                return BB622_BURST_TIMEOUT;
            }
            return BB622_BURST_NONE;
        }
    }
    if (b->delivered >= BB622_IRQ_BURST_MAX) {
        b->active = 0; b->end_reason = BB622_BURST_FINISHED;
        return BB622_BURST_FINISHED;
    }
    if (!(flags & 0x0200u) || (isr & 1u)) return BB622_BURST_NONE;
    if (b->last_try_us && now - b->last_try_us < BB622_IRQ_BURST_RETRY_US)
        return BB622_BURST_NONE;
    if (b->delivered && now - b->delivered_us < BB622_IRQ_BURST_GAP_US)
        return BB622_BURST_NONE;
    return BB622_BURST_DELIVER;
}
#endif
