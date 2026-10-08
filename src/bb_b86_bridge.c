#include "bb_b86_bridge.h"
#include <string.h>

uint32_t bb_b86_addr20(uint16_t segment, uint16_t offset)
{
    return (((uint32_t)segment << 4) + offset) & 0xFFFFFu;
}

int bb_b86_bridge_init(BbB86Bridge *b, MdRuntime *rt, uint8_t *memory, size_t memory_size)
{
    if (!b || !rt || !memory || memory_size < B86_MEM_BYTES || rt->cpu.memory != memory)
        return 0;
    memset(b, 0, sizeof(*b));
    b->runtime = rt;
    b86_init(&b->cpu, memory);
    /* Register mapping checked below. This does not certify address semantics. */
    b->ready = 1;
    bb_b86_load(b);
    return 1;
}

void bb_b86_load(BbB86Bridge *b)
{
    MdX86 *m;
    unsigned i;
    if (!b || !b->ready) return;
    m = &b->runtime->cpu;
    for (i = 0; i < 8; ++i) b->cpu.r[i] = m->r[i];
    b86_set_seg(&b->cpu, B86_ES, m->es);
    b86_set_seg(&b->cpu, B86_CS, m->cs);
    b86_set_seg(&b->cpu, B86_SS, m->ss);
    b86_set_seg(&b->cpu, B86_DS, m->ds);
    b->cpu.ip = m->ip;
    b86_set_flags(&b->cpu, md_x86_flags(m));
}

void bb_b86_save(BbB86Bridge *b)
{
    MdX86 *m;
    unsigned i;
    if (!b || !b->ready) return;
    m = &b->runtime->cpu;
    for (i = 0; i < 8; ++i) m->r[i] = (uint16_t)b->cpu.r[i];
    m->es = (uint16_t)b->cpu.seg[B86_ES];
    m->cs = (uint16_t)b->cpu.seg[B86_CS];
    m->ss = (uint16_t)b->cpu.seg[B86_SS];
    m->ds = (uint16_t)b->cpu.seg[B86_DS];
    m->ip = (uint16_t)b->cpu.ip;
    md_x86_set_flags(m, b86_get_flags(&b->cpu));
    ++b->committed;
}

int bb_b86_state_equal(BbB86Bridge *b)
{
    MdX86 *m;
    unsigned i;
    uint16_t mask = 0x0FD7u; /* defined 8086 FLAGS + IF/DF/TF */
    if (!b || !b->ready) return 0;
    m = &b->runtime->cpu;
    for (i = 0; i < 8; ++i) if (m->r[i] != (uint16_t)b->cpu.r[i]) return 0;
    if (m->es != (uint16_t)b->cpu.seg[B86_ES] ||
        m->cs != (uint16_t)b->cpu.seg[B86_CS] ||
        m->ss != (uint16_t)b->cpu.seg[B86_SS] ||
        m->ds != (uint16_t)b->cpu.seg[B86_DS] ||
        m->ip != (uint16_t)b->cpu.ip) return 0;
    return ((md_x86_flags(m) ^ b86_get_flags(&b->cpu)) & mask) == 0;
}
