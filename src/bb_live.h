#ifndef BB_LIVE_H
#define BB_LIVE_H
#include "microdos/runtime.h"
#include <stdint.h>
int bb_live_try(MdRuntime *rt);
uint64_t bb_live_retired(void);
uint64_t bb_live_blocks(void);
int bb_live_ready(void);
void bb_live_diag(uint64_t *attempts, uint64_t *candidates, uint64_t *inits, uint64_t *initfails,
                  uint64_t *runfails, uint16_t *cs, uint16_t *ip, uint8_t *op);
const char *bb_live_diff_field(void);
uint16_t bb_live_diff_expected(void);
uint16_t bb_live_diff_actual(void);
void bb_live_status(int *rc, uint64_t *delta, uint16_t *expected_ip, uint16_t *actual_ip,
                    uint64_t *verified, uint64_t *fallback, uint64_t *disabled,
                    uint64_t *budget, uint64_t *exit_count, uint64_t *halt, uint64_t *other);
#endif
