/* bb_snd.c - BB_SND_V1: guest-side sound devices for blitzBUS.
 *
 *   Sound Blaster 2.0 DSP (base 220h, IRQ 5, 8-bit DMA channel 1)
 *   8237 DMA controller, 8-bit channels 0-3 (ports 00h-0Fh, pages 81h/82h/83h/87h)
 *   MPU-401 UART (base 330h: 330h data, 331h status/command)
 *
 * Core 0 owns every register. Playback is paced by real time: bb_snd_poll(now)
 * moves as many sample bytes as the DSP rate says have elapsed from guest memory
 * through the 8237 channel into a PCM queue, and raises the IRQ at the end of
 * each DSP block, as the card does. MPU-401 UART bytes go to a MIDI queue. Both
 * queues are single-producer (core 0) / single-consumer (core 1) rings; a full
 * PCM ring drops samples rather than stalling the guest's timing.
 *
 * Self-contained: guest memory, interrupt raising and the clock come from the
 * host through BbSndHost, so this file builds and is tested on a desktop.
 * BB_SND=0 compiles nothing. */
#ifndef BB_SND
#define BB_SND 1
#endif
#if BB_SND
#include <stdint.h>
#include <string.h>

#ifndef BB_SND_SB_BASE
#define BB_SND_SB_BASE 0x220u
#endif
#ifndef BB_SND_SB_IRQ
#define BB_SND_SB_IRQ 5u
#endif
#ifndef BB_SND_SB_DMA
#define BB_SND_SB_DMA 1u
#endif
#ifndef BB_SND_MPU_BASE
#define BB_SND_MPU_BASE 0x330u
#endif

typedef struct BbSndHost {
    /* copy n bytes of guest PHYSICAL memory at phys into dst; 0 if unmapped */
    int (*read_phys)(void *user, uint32_t phys, uint8_t *dst, uint32_t n);
    void (*raise_irq)(void *user, unsigned irq);
    void *user;
    /* optional (BB_SND_V2 diagnostics): every port access this module handles */
    void (*trace)(void *user, int out, uint16_t port, uint8_t val);
} BbSndHost;

/* single-producer / single-consumer byte ring (size: power of two) */
typedef struct BbSndRing {
    uint8_t *buf;
    uint32_t mask;
    volatile uint32_t head;            /* written by core 0 only */
    volatile uint32_t tail;            /* written by core 1 only */
    unsigned long dropped;
} BbSndRing;

static uint32_t bb_snd_ring_used(const BbSndRing *r)
{
    return __atomic_load_n(&r->head, __ATOMIC_ACQUIRE) - __atomic_load_n(&r->tail, __ATOMIC_ACQUIRE);
}
static uint32_t bb_snd_ring_put(BbSndRing *r, const uint8_t *src, uint32_t n)
{
    const uint32_t h = r->head, t = __atomic_load_n(&r->tail, __ATOMIC_ACQUIRE);
    const uint32_t room = (r->mask + 1u) - (h - t);
    uint32_t i, k = n < room ? n : room;
    for (i = 0; i < k; ++i) r->buf[(h + i) & r->mask] = src[i];
    __atomic_store_n(&r->head, h + k, __ATOMIC_RELEASE);
    r->dropped += n - k;
    return k;
}
/* consumer side (core 1) */
static uint32_t bb_snd_ring_get(BbSndRing *r, uint8_t *dst, uint32_t n)
{
    const uint32_t t = r->tail, h = __atomic_load_n(&r->head, __ATOMIC_ACQUIRE);
    uint32_t i, k = (h - t) < n ? (h - t) : n;
    for (i = 0; i < k; ++i) dst[i] = r->buf[(t + i) & r->mask];
    __atomic_store_n(&r->tail, t + k, __ATOMIC_RELEASE);
    return k;
}

typedef struct BbDmaCh {
    uint16_t base_addr, base_count, cur_addr, cur_count;
    uint8_t page, mode, masked, tc;
} BbDmaCh;

typedef struct BbSnd {
    BbSndHost host;
    BbSndRing pcm, midi;
    /* 8237 */
    BbDmaCh ch[4];
    uint8_t ff;                        /* byte-pointer flip-flop */
    /* DSP */
    uint8_t in_reset, cmd, need, have, args[3];
    uint8_t outq[16], out_h, out_t, last_out;
    uint8_t speaker, test_reg, irq_pending;
    uint8_t dma_on, dma_auto, dma_paused, dma_exit_auto, dma_hs;
    uint16_t block_size;               /* 0x48: length - 1 */
    uint32_t dsp_left;                 /* bytes left in the current DSP block */
    uint32_t rate_hz;                  /* current output rate */
    volatile uint32_t pcm_rate_hz;     /* published for core 1 */
    uint64_t last_us;
    uint64_t frac;                     /* sub-sample remainder, units of 1/1e6 sample */
    /* MPU-401 */
    uint8_t mpu_uart, mpu_q[8], mpu_h, mpu_t;
    /* statistics */
    unsigned long n_irq, n_blocks, n_bytes, n_cmds, n_unknown, n_midi;
    /* BB_SND_V3 diagnostics: guest DMA bytes that were not silence (before any
     * speaker muting), speaker on/off commands, DSP resets */
    unsigned long n_guest_loud, n_spk_on, n_spk_off, n_resets;
} BbSnd;

static const uint8_t bb_snd_page_port[4] = { 0x87u, 0x83u, 0x81u, 0x82u };

static void bb_snd_out(BbSnd *s, uint8_t v)
{
    const uint8_t n = (uint8_t)((s->out_h + 1u) & 15u);
    if (n == s->out_t) return;         /* full: the oldest stays */
    s->outq[s->out_h] = v; s->out_h = n;
}
static void bb_snd_dsp_reset(BbSnd *s)
{
    s->cmd = 0; s->need = s->have = 0;
    s->out_h = s->out_t = 0;
    s->dma_on = s->dma_auto = s->dma_paused = s->dma_exit_auto = s->dma_hs = 0;
    s->irq_pending = 0; s->speaker = 0;
    s->dsp_left = 0;
    ++s->n_resets;
    bb_snd_out(s, 0xAAu);
}
static void bb_snd_init(BbSnd *s, const BbSndHost *host, uint8_t *pcm_buf, uint32_t pcm_size,
                        uint8_t *midi_buf, uint32_t midi_size, uint64_t now_us)
{
    memset(s, 0, sizeof *s);
    s->host = *host;
    s->pcm.buf = pcm_buf; s->pcm.mask = pcm_size - 1u;
    s->midi.buf = midi_buf; s->midi.mask = midi_size - 1u;
    for (unsigned i = 0; i < 4u; ++i) s->ch[i].masked = 1u;
    s->rate_hz = s->pcm_rate_hz = 11025u;
    s->block_size = 0x7FFu;
    s->last_us = now_us;
    s->last_out = 0xFFu;
}

/* ------------------------------------------------------------- 8237 DMA */
static int bb_snd_dma_in(BbSnd *s, uint16_t port, uint8_t *v)
{
    if (port <= 0x07u) {
        BbDmaCh *c = &s->ch[port >> 1];
        const uint16_t w = (port & 1u) ? c->cur_count : c->cur_addr;
        *v = s->ff ? (uint8_t)(w >> 8) : (uint8_t)w;
        s->ff ^= 1u;
        return 1;
    }
    if (port == 0x08u) {                                   /* status: TC bits, cleared on read */
        uint8_t st = 0;
        for (unsigned i = 0; i < 4u; ++i) { if (s->ch[i].tc) st |= (uint8_t)(1u << i); s->ch[i].tc = 0; }
        *v = st; return 1;
    }
    if (port == 0x0Fu) {                                   /* mask register (AT read-back) */
        uint8_t m = 0;
        for (unsigned i = 0; i < 4u; ++i) if (s->ch[i].masked) m |= (uint8_t)(1u << i);
        *v = (uint8_t)(0xF0u | m); return 1;
    }
    if (port <= 0x0Fu) { *v = 0xFFu; return 1; }
    for (unsigned i = 0; i < 4u; ++i)
        if (port == bb_snd_page_port[i]) { *v = s->ch[i].page; return 1; }
    return 0;
}
static int bb_snd_dma_out(BbSnd *s, uint16_t port, uint8_t v)
{
    if (port <= 0x07u) {
        BbDmaCh *c = &s->ch[port >> 1];
        uint16_t *b = (port & 1u) ? &c->base_count : &c->base_addr;
        uint16_t *cur = (port & 1u) ? &c->cur_count : &c->cur_addr;
        *b = s->ff ? (uint16_t)((*b & 0x00FFu) | ((uint16_t)v << 8)) : (uint16_t)((*b & 0xFF00u) | v);
        *cur = *b;
        s->ff ^= 1u;
        return 1;
    }
    switch (port) {
    case 0x08u: case 0x09u: return 1;                      /* command, request: not modelled */
    case 0x0Au: s->ch[v & 3u].masked = (uint8_t)((v >> 2) & 1u); return 1;
    case 0x0Bu: s->ch[v & 3u].mode = v; return 1;
    case 0x0Cu: s->ff = 0; return 1;
    case 0x0Du: s->ff = 0; for (unsigned i = 0; i < 4u; ++i) { s->ch[i].masked = 1u; s->ch[i].tc = 0; } return 1;
    case 0x0Eu: for (unsigned i = 0; i < 4u; ++i) s->ch[i].masked = 0; return 1;
    case 0x0Fu: for (unsigned i = 0; i < 4u; ++i) s->ch[i].masked = (uint8_t)((v >> i) & 1u); return 1;
    default: break;
    }
    for (unsigned i = 0; i < 4u; ++i)
        if (port == bb_snd_page_port[i]) { s->ch[i].page = v; return 1; }
    return 0;
}
/* Read up to n bytes through a channel; honours auto-init (mode bit 4) and
 * decrement (bit 5). Returns bytes moved; stops at terminal count otherwise. */
static uint32_t bb_snd_dma_read(BbSnd *s, unsigned chn, uint8_t *dst, uint32_t n)
{
    BbDmaCh *c = &s->ch[chn];
    uint32_t done = 0;
    if (c->masked || ((c->mode >> 2) & 3u) != 2u) return 0;   /* must be unmasked, memory -> I/O */
    while (done < n) {
        const uint32_t phys = ((uint32_t)c->page << 16) | c->cur_addr;
        uint8_t b = 0x80u;
        if (!s->host.read_phys(s->host.user, phys, &b, 1u)) b = 0x80u;
        dst[done++] = b;
        c->cur_addr = (c->mode & 0x20u) ? (uint16_t)(c->cur_addr - 1u) : (uint16_t)(c->cur_addr + 1u);
        if (c->cur_count-- == 0u) {                        /* terminal count */
            c->tc = 1u;
#if defined(BB_SND_MUT) && BB_SND_MUT == 1   /* test-only mutation: no auto-init reload */
            if (0) { }
#else
            if (c->mode & 0x10u) { c->cur_addr = c->base_addr; c->cur_count = c->base_count; }
#endif
            else { c->masked = 1u; break; }
        }
    }
    return done;
}

/* ------------------------------------------------------------- DSP */
static void bb_snd_start_dma(BbSnd *s, uint32_t len, int autoinit, int hs)
{
    s->dma_on = 1; s->dma_auto = (uint8_t)autoinit; s->dma_hs = (uint8_t)hs;
    s->dma_paused = 0; s->dma_exit_auto = 0;
    s->dsp_left = len;
    s->frac = 0;
    ++s->n_blocks;
}
static void bb_snd_set_rate(BbSnd *s, uint32_t hz)
{
    if (hz < 4000u) hz = 4000u;
    if (hz > 48000u) hz = 48000u;
    s->rate_hz = hz;
    __atomic_store_n(&s->pcm_rate_hz, hz, __ATOMIC_RELEASE);
}
static uint8_t bb_snd_params(uint8_t cmd)
{
    switch (cmd) {
    case 0x10u: case 0x38u: case 0x40u: case 0xE0u: case 0xE4u: return 1;
    case 0x14u: case 0x16u: case 0x17u: case 0x24u: case 0x41u: case 0x42u: case 0x48u:
    case 0x74u: case 0x75u: case 0x76u: case 0x77u: case 0x80u: return 2;
    default: return 0;
    }
}
static void bb_snd_exec(BbSnd *s, uint8_t cmd, const uint8_t *a)
{
    const uint32_t len16 = (uint32_t)a[0] | ((uint32_t)a[1] << 8);
    ++s->n_cmds;
    switch (cmd) {
    case 0x10u: bb_snd_ring_put(&s->pcm, &a[0], 1u); break;             /* direct DAC */
    case 0x14u: case 0x16u: case 0x17u: case 0x74u: case 0x75u: case 0x76u: case 0x77u:
        bb_snd_start_dma(s, len16 + 1u, 0, 0); break;                    /* single-cycle (ADPCM played as 8-bit) */
    case 0x1Cu: case 0x1Fu: case 0x7Cu: case 0x7Du: case 0x7Eu: case 0x7Fu:
        bb_snd_start_dma(s, (uint32_t)s->block_size + 1u, 1, 0); break;  /* auto-init */
    case 0x90u: bb_snd_start_dma(s, (uint32_t)s->block_size + 1u, 1, 1); break;   /* high speed auto-init */
    case 0x91u: bb_snd_start_dma(s, (uint32_t)s->block_size + 1u, 0, 1); break;   /* high speed single */
    case 0x40u: bb_snd_set_rate(s, 1000000u / (256u - a[0])); break;
    case 0x41u: case 0x42u: bb_snd_set_rate(s, ((uint32_t)a[0] << 8) | a[1]); break;
    case 0x48u: s->block_size = (uint16_t)len16; break;
    case 0x80u: s->dsp_left = 0; s->dma_on = 0; s->irq_pending = 1;      /* silence block: IRQ */
                s->host.raise_irq(s->host.user, BB_SND_SB_IRQ); ++s->n_irq; break;
    case 0xD0u: s->dma_paused = 1; break;
    case 0xD4u: s->dma_paused = 0; break;
    case 0xD1u: s->speaker = 1; ++s->n_spk_on; break;
    case 0xD3u: s->speaker = 0; ++s->n_spk_off; break;
    case 0xD8u: bb_snd_out(s, s->speaker ? 0xFFu : 0x00u); break;
    case 0xDAu: s->dma_exit_auto = 1; break;
    case 0x20u: bb_snd_out(s, 0x80u); break;                             /* direct ADC: silence */
    case 0x38u: break;                                                   /* MIDI out (SB) - ignored */
    case 0xE0u: bb_snd_out(s, (uint8_t)~a[0]); break;
    case 0xE1u: bb_snd_out(s, 0x02u); bb_snd_out(s, 0x01u); break;       /* DSP 2.01 */
    case 0xE4u: s->test_reg = a[0]; break;
    case 0xE8u: bb_snd_out(s, s->test_reg); break;
    case 0xF2u: s->irq_pending = 1; s->host.raise_irq(s->host.user, BB_SND_SB_IRQ); ++s->n_irq; break;
    default: ++s->n_unknown; break;
    }
}
static void bb_snd_dsp_write(BbSnd *s, uint8_t v)
{
    if (s->dma_hs && s->dma_on) return;                    /* high-speed mode ignores writes until it ends */
    if (s->need) {
        s->args[s->have++] = v;
        if (s->have == s->need) { s->need = 0; bb_snd_exec(s, s->cmd, s->args); }
        return;
    }
    s->cmd = v; s->have = 0; s->need = bb_snd_params(v);
    if (!s->need) bb_snd_exec(s, v, s->args);
}

/* ------------------------------------------------------------- MPU-401 */
static void bb_snd_mpu_ack(BbSnd *s)
{
    const uint8_t n = (uint8_t)((s->mpu_h + 1u) & 7u);
    if (n != s->mpu_t) { s->mpu_q[s->mpu_h] = 0xFEu; s->mpu_h = n; }
}

/* ------------------------------------------------------------- ports */
static int bb_snd_port_in_raw(BbSnd *s, uint16_t port, uint8_t *v)
{
    if (port >= BB_SND_SB_BASE && port <= BB_SND_SB_BASE + 0x0Fu) {
        switch (port - BB_SND_SB_BASE) {
        case 0x0Au:                                        /* read data */
            if (s->out_t != s->out_h) { s->last_out = s->outq[s->out_t]; s->out_t = (uint8_t)((s->out_t + 1u) & 15u); }
            *v = s->last_out; return 1;
        case 0x0Cu: *v = 0x7Fu; return 1;                  /* write status: always ready (bit 7 = 0) */
        case 0x0Eu:                                        /* read status; acknowledges the 8-bit IRQ */
            s->irq_pending = 0;
            *v = (uint8_t)((s->out_t != s->out_h ? 0x80u : 0x00u) | 0x7Fu); return 1;
        default: *v = 0xFFu; return 1;
        }
    }
    if (port == BB_SND_MPU_BASE) {
        if (s->mpu_t != s->mpu_h) { *v = s->mpu_q[s->mpu_t]; s->mpu_t = (uint8_t)((s->mpu_t + 1u) & 7u); }
        else *v = 0xFFu;
        return 1;
    }
    if (port == BB_SND_MPU_BASE + 1u) {                    /* bit 7 = 0: data to read; bit 6 = 0: ready */
        *v = (uint8_t)((s->mpu_t != s->mpu_h) ? 0x3Fu : 0xBFu); return 1;
    }
    return bb_snd_dma_in(s, port, v);
}
static int bb_snd_port_out_raw(BbSnd *s, uint16_t port, uint8_t v)
{
    if (port >= BB_SND_SB_BASE && port <= BB_SND_SB_BASE + 0x0Fu) {
        switch (port - BB_SND_SB_BASE) {
        case 0x06u:
            if (v & 1u) s->in_reset = 1;
            else if (s->in_reset) { s->in_reset = 0; bb_snd_dsp_reset(s); }
            return 1;
        case 0x0Cu: bb_snd_dsp_write(s, v); return 1;
        default: return 1;
        }
    }
    if (port == BB_SND_MPU_BASE) {
        if (s->mpu_uart) { bb_snd_ring_put(&s->midi, &v, 1u); ++s->n_midi; }
        return 1;
    }
    if (port == BB_SND_MPU_BASE + 1u) {
        if (v == 0x3Fu) s->mpu_uart = 1;
        else if (v == 0xFFu) s->mpu_uart = 0;
        bb_snd_mpu_ack(s);
        return 1;
    }
    return bb_snd_dma_out(s, port, v);
}

static int bb_snd_port_in(BbSnd *s, uint16_t port, uint8_t *v)
{
    const int r = bb_snd_port_in_raw(s, port, v);
    if (r && s->host.trace) s->host.trace(s->host.user, 0, port, *v);
    return r;
}
static int bb_snd_port_out(BbSnd *s, uint16_t port, uint8_t v)
{
    const int r = bb_snd_port_out_raw(s, port, v);
    if (r && s->host.trace) s->host.trace(s->host.user, 1, port, v);
    return r;
}

/* ------------------------------------------------------------- real time */
static void bb_snd_poll(BbSnd *s, uint64_t now_us)
{
    uint8_t tmp[64];
    if (now_us <= s->last_us) return;
    const uint64_t dt = now_us - s->last_us;
    s->last_us = now_us;
    if (!s->dma_on || s->dma_paused || !s->dsp_left) { s->frac = 0; return; }
    s->frac += dt * (uint64_t)s->rate_hz;                  /* in 1e-6 samples */
    uint64_t due = s->frac / 1000000u;
    s->frac -= due * 1000000u;
    if (due > 4096u) due = 4096u;                          /* a stalled host: do not burst more */
    while (due && s->dma_on) {
        uint32_t want = s->dsp_left < due ? s->dsp_left : (uint32_t)due;
        if (want > sizeof tmp) want = sizeof tmp;
        const uint32_t got = bb_snd_dma_read(s, BB_SND_SB_DMA, tmp, want);
        if (!got) { s->dma_on = 0; break; }               /* channel masked or not set up */
        for (uint32_t i = 0; i < got; ++i) if (tmp[i] < 126u || tmp[i] > 130u) ++s->n_guest_loud;
        if (s->speaker || s->dma_hs) bb_snd_ring_put(&s->pcm, tmp, got);
        else { memset(tmp, 0x80, got); bb_snd_ring_put(&s->pcm, tmp, got); }
        s->n_bytes += got;
        s->dsp_left -= got; due -= got;
        if (!s->dsp_left) {                                /* end of DSP block: IRQ */
            s->irq_pending = 1;
#if !(defined(BB_SND_MUT) && BB_SND_MUT == 2)   /* test-only mutation: no IRQ at block end */
            s->host.raise_irq(s->host.user, BB_SND_SB_IRQ);
#endif
            ++s->n_irq;
            if (s->dma_auto && !s->dma_exit_auto) { s->dsp_left = (uint32_t)s->block_size + 1u; ++s->n_blocks; }
            else { s->dma_on = 0; s->dma_hs = 0; }
        }
    }
}
#endif /* BB_SND */
