# Design: one SRAM pool for both JITs

Status: design, not implemented. TODO.md item 3.

## Problem

Two kinds of programs need the same SRAM for different things:

| Program kind | Needs | Measured |
|---|---|---|
| Real mode (3DBench, real-mode games) | a large real-mode JIT code cache | 3DBench thrashes at 128 KB (score 00.0, 5.8 of 14.3 s translating), 219 KB still ~7% translating, 240 KB fine (40.0) |
| DOS/4GW, DJGPP (Descent, Doom, Quake) | the protected-mode SRAM hot tier | Descent: ~22% of core 0 runs from the tier with V120 |

Today the split is fixed at build time (`BB_CODE_KB`, `BB_PJ_HOT_KB`), worked
around with two build profiles (`scripts\bb_profile.ps1 rm|pm`). But a single
session runs both kinds: under the DPMI host, real mode only runs DOS calls,
so the protected-mode tier needs the space exactly when the real-mode JIT
doesn't, and vice versa.

## Today's memory

- `bb_code[BB_CODE_BYTES]` in `bb_live.c`: the real-mode JIT's code buffer.
  The JIT gets `buf`/`buf_end` once at attach (`jit.c`, `j->buf_end = code + size`)
  and manages it as a ring with region eviction (`evict_range`, `evict_step`,
  `evict_make_room`). `evict_range(j, lo, hi)` already removes every block in
  a range, unchains links into it and bumps `flush_gen`.
- `bb_pj_hot[BB_PJ_HOT_KB * 1024]`: the protected-mode hot tier, attached once
  with `b86_pj_attach_hot()`. `pj_hot_reset()` empties the tier and restores
  every redirect (guarded since V117c). There is no detach.
- `BB_PM_RAM`: places protected-mode C functions in SRAM or flash. That's
  code placement at link time and stays a build setting.

## Design

**One static pool** replaces both arrays:
`bb_pool[BB_CODE_KB_PM + BB_PJ_HOT_KB]`, e.g. 128 + 91 = 219 KB with today's
`pm` values. A movable split point divides it:

```
bb_pool:  [ real-mode JIT code ............ | protected-mode hot tier ]
          0                               split                     end
```

**Two states:**

| State | Real-mode JIT | Hot tier | When |
|---|---|---|---|
| RM | whole pool (219 KB) | detached | no DPMI client active |
| PM | `[0, split)`, 128 KB | `[split, end)`, 91 KB | a DPMI client is running |

**RM → PM** at DPMI client entry (`dpmi_host.c`, where `g_active = 1`):
1. Real-mode JIT: `evict_range(j, split, end)`, then `buf_end = split`
   (new API: `b86_jit_set_end(c, end)`; it must also move the ring's
   `free_end`/`e.p` back below `split` if they are above it).
2. Protected-mode JIT: attach the hot tier at `[split, end)`
   (`b86_pj_attach_hot`, which must accept a second attach after a detach).

**PM → RM** at DPMI client exit:
1. Protected-mode JIT: detach the hot tier (new API: `b86_pj_detach_hot(c)`):
   `pj_hot_reset()` semantics (every redirect restored, every stub into the
   tier unlinked), then `j->hot = NULL`, `hot_cap = 0`. Promotion and the
   sample drain already check `j->hot`.
2. Real-mode JIT: `buf_end = end` (`b86_jit_set_end`). Growing needs no
   eviction.

**Detecting the exit:** the host does not track it today (`g_active` stays 1).
A client exits with `INT 21h AH=4Ch` from protected mode, which the host
reflects to DOS. The host sees it in its INT 21h path: on `AH=4Ch` from the
client, mark the client inactive and run the PM → RM handover after the
reflection returns.

**Only at these two events.** Real-mode calls during a DPMI session (DOS
reads, BIOS) use the smaller real-mode cache, as with the `pm` profile today.
No handover per mode switch: that would thrash both caches.

## Why it's safe

- Both handovers run in C at host trap points; no native code from either
  cache is executing.
- Eviction in the real-mode JIT is the existing path the ring uses all the
  time; it already unchains links into the evicted range.
- Detaching the hot tier is `pj_hot_reset()`, which already restores every
  redirect, plus clearing the tier pointers.
- The protected-mode JIT's PSRAM code cache is untouched; blocks only move
  back from SRAM to their PSRAM copies.

## Trade-off

The pool is sized by the `pm` profile (219 KB), with `BB_PM_RAM=1`. Real-mode
programs then get 219 KB instead of the `rm` profile's 240 KB (3DBench: about
7% translation at 219 KB). If that matters, a larger pool needs SRAM from
elsewhere; candidate: the real-mode JIT's separate 40 KB `bb_hot` buffer (to
be checked: what it holds and whether it could be part of the pool).

## Steps

1. `b86_jit_set_end()` in `jit.c` (shrink with eviction, grow), with a test
   that shrinks and grows repeatedly under load and compares the guest state
   with an unchanged run.
2. `b86_pj_detach_hot()` and re-attach in `i386_pj.inc`, with a fuzz test of
   attach/detach cycles while blocks are promoted and linked.
3. Exit detection in `dpmi_host.c` (`AH=4Ch` from the client).
4. `bb_pool` and the two handovers in `bb_live.c`; one firmware for both
   kinds of programs.
5. On the Pico: 3DBench, then Descent, then 3DBench again in one session,
   checking scores and stability against the two profiles.
