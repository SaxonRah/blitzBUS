#ifndef BB622_IRQ0_CADENCE_H
#define BB622_IRQ0_CADENCE_H
/* DOS 6.22 opt-in real PIT cadence experiment. No extra PIC/PIT model.
   The host schedules only at guest slice boundaries; no asynchronous mutation.
   Diagnostic-only. Normal DOS6 IRQ0 remains suppressed until Ctrl+L. */
#include <stdint.h>

#define BB622_CADENCE_WINDOW_US 10000000ull
#define BB622_CADENCE_EOI_STALL_US 1500000ull
#define BB622_CADENCE_REPORT_US 2000000ull

typedef struct Bb622IrqCadence {
    uint64_t started_us, reported_us, service_since_us;
    uint64_t start_edges, start_delivered, start_eois, start_coalesced;
    uint32_t start_bda;
    uint8_t active, in_service_seen, end_reason;
} Bb622IrqCadence;

enum { BB622_CADENCE_NONE=0, BB622_CADENCE_RUN=1,
       BB622_CADENCE_FINISH=2, BB622_CADENCE_STALL=3 };

static inline void bb622_cadence_reset(Bb622IrqCadence *c) {
    Bb622IrqCadence zero={0}; *c=zero;
}
static inline void bb622_cadence_arm(Bb622IrqCadence *c, uint64_t now,
                    uint64_t edges, uint64_t delivered, uint64_t eois,
                    uint64_t coalesced, uint32_t bda) {
    bb622_cadence_reset(c);
    c->active=1; c->started_us=now; c->reported_us=now;
    c->start_edges=edges; c->start_delivered=delivered;
    c->start_eois=eois; c->start_coalesced=coalesced; c->start_bda=bda;
}
/* Must be called at CPU slice boundaries, not in an ISR or background task.
   The real bb_irq36_dispatch() retains PIC ISR, IF, IMR and PIT edge checks. */
static inline int bb622_cadence_poll(Bb622IrqCadence *c, uint64_t now,
                                    uint8_t isr, uint8_t auto_eoi) {
    if (!c->active) return BB622_CADENCE_NONE;
    if (now<c->started_us) {
        c->active=0; c->end_reason=BB622_CADENCE_STALL;
        return BB622_CADENCE_STALL;
    }
    if (!auto_eoi && (isr&1u)) {
        if (!c->in_service_seen) {
            c->service_since_us=now; c->in_service_seen=1;
        } else if (now<c->service_since_us ||
                   now-c->service_since_us>=BB622_CADENCE_EOI_STALL_US) {
            c->active=0; c->end_reason=BB622_CADENCE_STALL;
            return BB622_CADENCE_STALL;
        }
    } else {
        c->in_service_seen=0;
    }
    if (now-c->started_us>=BB622_CADENCE_WINDOW_US) {
        c->active=0; c->end_reason=BB622_CADENCE_FINISH;
        return BB622_CADENCE_FINISH;
    }
    return BB622_CADENCE_RUN;
}
#endif
