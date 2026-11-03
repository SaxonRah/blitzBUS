# blitzBUS DPMI Host — Design

Nov 3, 2026 · @ParabolicLabs

## Why

With sound on, DOS/4GW's own kernel takes 58% of core 0 and Descent gets 23%; a native DPMI host replaces that kernel work with C.

Measured on the Pico Plus 2 (runs of 2–3 November 2026, Descent demo, Sound Blaster + music on, BB\_PM\_IRQ0=1):

| What | Measured | Where it goes |
| --- | --- | --- |
| Guest speed | 0.60 MIPS with sound, 2.67 without | 4.4× slowdown |
| Protected-mode interrupts | \~1,100 per second (IRQ0 at 120 Hz + IRQ5) | each \~0.5 ms ≈ 180,000 cycles through DOS/4GW's 16-bit path |
| DOS/4GW kernel segments (0070, 0080, 0088, 3E58, 0018) | 58% of core 0 | 18% JIT lookups/epochs, 16% other C, 15% interpreter, 10% native |
| Real-mode round trips | \~25 per second (17 BIOS ticks + DOS calls) | \~9% of core 0, almost all JIT epoch work after CR0/CR3 writes |
| HMI driver (0300, 02D8) | \~13% of core 0 | half interpreted (own data segment) |
| Mode switches, task switches, page faults | 25/s, <1/s, <1/s | not the problem by count, only by cost per event |

Under a DPMI host the client never touches CR0, CR3, LTR or the TSS, never builds the 0080 interrupt frame, and never runs its virtual-memory kernel: those paths are the 58% and the 9%. The host's own cost is native C, a few microseconds per interrupt.

## Goals and non-goals

The host must run Descent (DOS/4GW 1.97) with sound at close to no-sound speed, and must not change the game's behaviour in any way we can observe.

Goals, in priority order:

1. Correctness first: every DPMI 0.9 function the client calls behaves per spec; anything unimplemented returns the spec's error (CF=1, AX=8001h) rather than guessing.
2. Hardware interrupts delivered from C straight to the client's handler: no guest-side kernel path, no stack-frame copies, no segment probing.
3. Real-mode services (INT 21h, INT 13h, BIOS ticks) done by the host with no CR0/CR3 writes by the guest: the emulator switches mode internally.
4. No paging for the client by default (linear = physical), so the JIT runs without epochs caused by mapping changes.
5. The same host serves DOS/32A, PMODE/W, CWSDPMI-expecting DJGPP programs (Quake, Doom's DOS builds) later; nothing in the design is Descent-specific.

Non-goals for the first version:

- DPMI 1.0 extensions, 16-bit (286) clients, Windows-style multiple virtual machines.
- Demand paging or swapping. Guest RAM is 4 MB; programs needing more fail cleanly at allocation.
- Hardware virtualization of the PIC, PIT or DMA beyond what blitzBUS already emulates; the host only changes who receives interrupts.
- Replacing microDOS/DOS 6.22 real-mode services; the host calls them.

## The client contract: how DOS/4GW uses a DPMI host

DOS/4GW switches itself into "DPMI client" mode at start-up when INT 2Fh AX=1687h reports a host; from then on it uses the host for everything below and keeps only its own INT 21h parameter translation layer.

Sequence at start-up (DPMI 0.9 specification, chapter 3):

1. INT 2Fh AX=1687h → AX=0 (host present), BX=flags (bit 0: 32-bit clients supported), CL=CPU type (4 = 486), DH:DL=version (0.90), SI=paragraphs of host private data needed, ES:DI=entry point.
2. The client allocates SI paragraphs of DOS memory, puts ES at that block, sets AX bit 0 for a 32-bit client, and far-calls ES:DI. The host returns in protected mode with CS/DS/SS/ES mapped to the client's real-mode segments (CS and SS 32-bit per bit 0), with CF=0.
3. From then on the client calls INT 31h for descriptors, memory, vectors and real-mode services, and expects interrupts and exceptions to arrive on its protected-mode handlers.

What DOS/4GW is known to rely on (its behaviour under Windows 3.x/95 DOS boxes, and what the disassembly of 0080/3E58 shows it doing itself today):

- LDT descriptors for its code, data and the application's flat 32-bit segments (functions 0000h–000Ch); the application's selectors 0268/0270 become LDT selectors.
- Linear memory for the application image and heap (0500h–0503h), DOS memory for its real-mode buffer (0100h–0102h).
- Hardware-interrupt handlers installed with 0205h (HMI installs IRQ0 and IRQ5 this way through DOS/4GW), real-mode vectors read and set with 0200h/0201h, exception handlers with 0203h.
- Simulate real-mode interrupt (0300h) for DOS and BIOS calls it does not handle itself; real-mode callbacks (0303h/0304h) for real-mode code that must call protected mode (none seen in Descent so far; HMI's digital driver stays in protected mode).
- Virtual interrupt state (0900h–0902h): the client toggles IF through the host, never with CLI/STI semantics of its own.
- Get version (0400h) and lock/unlock linear region (0600h/0601h), which succeed trivially without paging.

Open question: whether Descent's DOS/4GW honours `DOS16M` settings that disable DPMI detection; the default is to use DPMI when present.

## Architecture

The host is one C module in flash, `bb_dpmi.c`, reached through trap opcodes in guest memory and owning the descriptor tables, the client's memory and the interrupt routing.

&#91;embedded content: host architecture · 4 host modules between the guest and the two CPU engines\]

The client enters the host through INT 31h and leaves with results in registers; interrupts enter the host from the PIC and leave as a direct call into the handler the client installed.

**Trap mechanism.** blitzBUS already intercepts BIOS and DOS vectors in real mode with a hook opcode (`bb622_watch_bios`, `hook_int`). The host extends that to protected mode: every IDT entry the client does not own points at a 4-byte stub in a host-owned code segment whose first instruction is the hook opcode; the interpreter and the JIT already treat that opcode as a C call-out (the JIT declines the block, the interpreter dispatches to `bb_dpmi_trap(vector)`). INT 2Fh in real mode is hooked the same way blitzBUS hooks INT 21h today.

**Descriptor model.** The host owns GDT, LDT and IDT in guest memory it allocates at start-up (DOS memory, below 1 MB, so real-mode code can reach it). The client gets LDT selectors (table bit set, RPL 3 in the selector but ring 0 in practice: the emulator runs the client at CPL 0 with no privilege checks between host and client, which DPMI permits; see Risks). Fixed GDT entries: null, host code 16, host data 16, host stack, client code 32 flat, client data 32 flat, TSS placeholder. The LDT has 512 entries (4 KB), enough for DOS/4GW's own use plus the application's selectors.

**Memory model.** Linear = physical, no paging (CR0.PG stays 0). Linear allocations (0501h) come from a host pool above DOS/4GW's image, managed as a first-fit free list in PSRAM metadata, returned with a handle = base address. DOS memory (0100h) is allocated through the real-mode DOS allocator by a bridged INT 21h AH=48h call, so DOS's own arena stays consistent.

**State.** Per client: the LDT, the handler table for vectors 00h–FFh (PM selector:offset or "not hooked"), the real-mode vector shadow, the virtual IF, the locked PM stack for hardware interrupts, and the entry state saved at the mode-switch entry point. One client at a time (DOS/4GW spawning a child extender is a non-goal).

## Interrupt delivery: the hot path

A hardware interrupt becomes one C function that builds the handler's frame and jumps to it; the target is 3–5 µs per interrupt instead of \~500 µs today.

Today (raw mode) one IRQ0 runs: 0070 stub → far jump → 0080 entry (frame, LAR probes, CS: tables, 712-byte save area, stack switch) → dispatcher → `PUSH/RETF` into HMI → return path with two stack switches → `IRET`. Under the host:

1. `bb386_pmirq_poll` sees an unmasked IRQ with the client's virtual IF set. It calls `bb_dpmi_deliver(irq)` instead of pushing a frame for the guest IDT.
2. The host switches to the locked PM interrupt stack if the client is on a real-mode or host stack; otherwise it stays on the client's stack (DPMI 0.9 permits either; DOS/4GW's handlers assume a 32-bit stack, matched by the client's SS size from step 2 of the start-up sequence).
3. It pushes the 32-bit `IRET` frame the handler expects (EFLAGS, CS, EIP of the interrupted code) plus a return frame pointing at the host's "interrupt return" stub (hook opcode), and sets CS:EIP to the handler the client installed with 0205h. Interrupts are virtually disabled (virtual IF = 0) and the PIC's in-service bit is set as today.
4. Native execution resumes in the JIT at the handler. For HMI's IRQ0 handler that is based 32-bit code already compiled by V114–V116; the mixer runs natively and chained.
5. The handler's `IRET` hits the return stub: the host pops its frame, restores the virtual IF from the saved EFLAGS, re-checks pending IRQs and resumes the interrupted code. The handler's own EOI goes to the emulated PIC unchanged.

Vectors the client has not hooked (keyboard INT 09h before the game installs its own, INT 08h chaining) are reflected to real mode by the host: a real-mode interrupt simulated through the bridge, then return. Software interrupts from protected mode (INT 21h issued by the client's translation layer, INT 10h, INT 33h) go the same way unless the client hooked them with 0205h.

| Per interrupt today (measured) | Under the host (estimate) |
| --- | --- |
| \~150–250 guest instructions in 16-bit kernel code, mostly interpreted | 0 guest instructions outside the handler |
| 2 stack switches, 2 LAR probes, 58-byte frame copy | 1 C frame build, \~60 bytes written |
| 4–8 JIT dispatches and lookups on the way in and out | 1 dispatch into the handler, 1 return |
| \~500 µs | 3–5 µs plus the handler's own work |

At \~1,100 interrupts per second that is roughly 50% of core 0 returned to the game, before counting the mode-switch savings.

## Real-mode services

A real-mode call becomes a mode set by the emulator, with no CR0, CR3, LTR or TSS activity by the guest: no TLB flush and no JIT epoch.

**Simulate real-mode interrupt (0300h) and call real-mode procedure (0301h/0302h).** The client passes a register structure (ES:EDI, 50 bytes: EDI, ESI, EBP, EBX, EDX, ECX, EAX, flags, ES, DS, FS, GS, IP, CS, SP, SS). The host:

1. Saves the client's protected-mode register state and the frame it entered with.
2. Loads the real-mode registers from the structure; if SS:SP is zero, uses the host's real-mode stack (DPMI requires at least 30 words; the host gives 1 KB).
3. Sets the emulator to real mode and runs the interrupt or far call through microDOS, exactly as blitzBUS runs real-mode code today. This is an engine hand-off (`bb386_pm_track`'s LEAVE/ENTER), but without the guest's 0018 switch code, so no paging toggle.
4. On return (the real-mode `IRET` or `RETF` reaches a host stub), copies the registers back into the structure, restores protected mode and the client's state, and returns to the client with CF=0.

Hardware interrupts arriving during real-mode execution are delivered to real-mode handlers if the client hooked none, or reflected up to the client's protected-mode handler through step 1–5 of interrupt delivery with a mode switch around it (the case today for IRQ0 arriving during a DOS call).

**Real-mode callbacks (0303h/0304h).** The host keeps 16 callback slots, each a 4-byte real-mode stub (hook opcode + slot number) in the host's DOS block. A real-mode caller reaching the stub traps into C; the host switches to protected mode, fills the client's register structure, and calls the client's callback procedure; its `IRET` returns through a host stub that switches back and continues the real-mode caller. Descent is not known to use these; DJGPP programs and some mouse drivers do.

**DOS memory (0100h–0102h).** Bridged to INT 21h AH=48h/49h/4Ah in real mode through the same path, so DOS's arena stays authoritative; the host returns the paragraph and allocates an LDT descriptor pair per 64 KB (DPMI requires consecutive selectors for blocks over 64 KB; the host allocates them from a reserved run).

**BIOS ticks.** The BIOS INT 08h stub stays as it is (host-maintained BDA tick); HMI chains to it \~17 times a second through the client's real-mode vector, which under the host means one 0300h-style reflection, now a cheap engine hand-off.

## INT 31h function set, by stage

Stage A is what DOS/4GW needs to start and run Descent; everything unlisted returns CF=1, AX=8001h (unsupported) and is logged once, so the census after the first runs tells us what stage B must add.

| Function | Name | Stage | Notes |
| --- | --- | --- | --- |
| 2Fh/1687h | Installation check | A | AX=0, BX=1 (32-bit), CL=4, DX=005Ah (0.90), SI=host paragraphs, ES:DI entry |
| entry point | Switch to protected mode | A | AX bit 0 = 32-bit client; returns in PM with CS/DS/SS/ES as LDT selectors |
| 0000h | Allocate LDT descriptors | A | consecutive run of CX descriptors |
| 0001h | Free LDT descriptor | A |  |
| 0002h | Segment to descriptor | A | cached per real-mode segment |
| 0003h | Get selector increment | A | 8 |
| 0006h / 0007h | Get / set segment base | A |  |
| 0008h | Set segment limit | A | granularity bit for limits over 1 MB |
| 0009h | Set descriptor access rights | A |  |
| 000Ah | Create alias descriptor | A |  |
| 000Bh / 000Ch | Get / set descriptor | A | 8 bytes raw |
| 0100h–0102h | DOS memory allocate / free / resize | A | bridged to INT 21h |
| 0200h / 0201h | Get / set real-mode vector | A | shadow table + real IVT |
| 0202h / 0203h | Get / set exception handler | A | #GP, #PF, #UD routed to client if set |
| 0204h / 0205h | Get / set protected-mode vector | A | the handler table used by delivery |
| 0300h | Simulate real-mode interrupt | A |  |
| 0301h / 0302h | Call real-mode procedure (RETF / IRET) | A |  |
| 0303h / 0304h | Allocate / free real-mode callback | B | 16 slots |
| 0305h / 0306h | Get state save/restore, raw switch addresses | B | DOS/4GW queries these; raw switch may return "unsupported" |
| 0400h | Get version | A | 0.90, flags bit 0 (32-bit), CPU 4, PIC bases 08h/70h |
| 0500h | Get free memory information | A | largest free block from the linear pool |
| 0501h / 0502h / 0503h | Allocate / free / resize linear memory | A | handle = base; resize may move (copy) |
| 0600h / 0601h | Lock / unlock linear region | A | no-op success |
| 0602h / 0603h | Mark real-mode region pageable / unpageable | A | no-op success |
| 0604h | Get page size | A | 4096 |
| 0800h / 0801h | Physical address mapping | B | identity (linear = physical) |
| 0900h / 0901h / 0902h | Get and disable / enable / query virtual IF | A |  |
| 0A00h | Get vendor API entry point | B | none; CF=1 |
| 0B00h–0B03h | Debug registers | — | unsupported |
| 0E00h / 0E01h | Coprocessor status / emulation | B | no-op (386 class, no x87 trap) |

Unknown at design time: which of 0305h/0306h DOS/4GW requires rather than merely queries. The census (Testing) answers that before stage A is frozen.

## Interaction with blitz86 and paging

The JIT needs no new instruction coverage for the host; it needs a cheap way in and out of C, and it loses the paging epochs entirely.

- **No paging.** With CR0.PG = 0 and linear = physical, `pj_flat` holds for the application's selectors (base 0, limit 4 GB) exactly as today, and V99's selective epochs are never triggered by mapping changes. The 9% measured in epoch work after CR0/CR3 writes disappears, as does `b86_pg_walk`.
- **Hook opcode in protected mode.** The host's stubs use the same undefined-opcode trap the real-mode hooks use. The 32-bit translator already declines blocks containing it (it falls under "unsupported"); the interpreter dispatches it to `bb_dpmi_trap()`. Cost: one block exit per trap, which is the same as a far call today.
- **Entering the handler.** Delivery writes the client's CS:EIP, SS:ESP and EFLAGS, then returns to the dispatcher loop, which finds the handler's block in the based-32 (V114) or flat tables. No JIT state is invalidated by delivery: descriptor caches are reloaded from the host's tables through the existing `b86_load_seg` path.
- **Mode hand-off for real-mode services.** blitzBUS already alternates between the blitz86 engine (protected mode) and microDOS (real mode) through `bb386_pm_track`. The bridge uses the same hand-off; because CR0 is not written by the guest, the JIT's protected-mode state (contexts, filters, code cache) stays valid across the round trip. Measured today: \~25 round trips per second with a full epoch each; under the host, 0 epochs.
- **Descriptor edits.** Functions 0007h–000Ch change descriptors the client may be using. The host writes the LDT entry and invalidates the CPU's cached descriptor for any selector currently loaded (CS, DS, ES, FS, GS, SS), which forces the existing V114 context switch if CS changed base or limit. The 16-bit contexts keyed by base/limit/kind (V97) handle this without new code.
- **LTR, task switches, CR3.** None under the host. The TSS exists only so that `LTR` by a legacy client does not fault; DOS/4GW as a DPMI client does not use it.
- **Interpreter fallbacks still needed.** DOS/4GW's own 16-bit kernel still runs its INT 21h translation layer (0080 segment code that handles buffer copies between the application's flat memory and the DOS transfer buffer). That stays interpreted or translated as today, but it runs only per DOS call (\~10/s), not per interrupt.

## SRAM and PSRAM budget

The host must fit in about 1.5 KB of SRAM: all its code goes to flash and its tables into guest memory or the PSRAM metadata pool.

SRAM today (firmware 44c212, after SRAM\_ROOM\_V3): about 1,590 bytes of code room before the 4 KB boundary and a heap 52 bytes above the 6,144 minimum. Rules the host follows, enforced by the build's heap check:

| Item | Where | Size |
| --- | --- | --- |
| Host code (`bb_dpmi.c`) | flash (`.text.bb_dpmi`, noinline) | \~12–20 KB flash, 0 SRAM |
| Delivery entry called from `bb386_pmirq_poll` | one call + veneer in SRAM | ≤ 16 bytes SRAM |
| GDT (8 entries), LDT (512 entries), IDT (256 entries) | guest DOS memory, host block | 64 + 4,096 + 2,048 bytes guest RAM |
| Host real-mode stack, PM interrupt stack, callback stubs | guest DOS memory | 1 KB + 4 KB + 64 bytes |
| Handler table (256 × 8), vector shadow, state | PSRAM metadata pool (`bb_meta_calloc`) | \~4.5 KB PSRAM |
| Linear pool free list | PSRAM metadata pool | 512 bytes |
| Pointers to the above | SRAM `.bss` | ≤ 16 bytes |

Guest memory for the host block comes from the paragraphs the client allocates at start-up (SI in the installation check): the host asks for 12 KB, which also keeps the tables below 1 MB for real-mode access. PSRAM is at 99.7%; the metadata pool (896 KB) has room for the \~5 KB above.

## Testing strategy

Every stage is proven on the host PC against the DPMI 0.9 text before it touches the Pico, with the same discipline as V113–V116: differential tests, deliberate mutations, exact-install packages.

1. **Census first, in the current firmware.** A diagnostic that logs every INT 2Fh 1687h and INT 31h call Descent's DOS/4GW would make if a host answered: impossible today, since it runs raw. Instead, run Descent under a known host on a PC (Windows 98 DOS box or DOSBox with its DPMI logging) and record the function census; that list freezes stage A. Cost: an afternoon, no code.
2. **Host unit tests in `pj_fuzz`.** The harness already builds blitz86 on the PC under qemu-arm. A new mode links `bb_dpmi.c` against a stub blitzBUS (PIC, memory, mode hand-off mocked) and drives it with hand-written client programs: allocate descriptors and check the LDT bytes; install a handler with 0205h, raise IRQ0, check the frame on the stack to the byte; 0300h with every register field; callbacks; error codes for unsupported functions.
3. **Mutations.** For each test, one deliberately broken host (wrong frame order, virtual IF not cleared, descriptor written to the wrong slot) must fail the test; a test that passes a mutation is not a test.
4. **A small DPMI client on the Pico.** A 200-line Watcom program (DOS/4GW-bound) that exercises the stage-A set, prints results through INT 21h and exits. First target on hardware; runs in seconds.
5. **Descent demo as the system test,** with the existing tooling: `demo_bench` for frames per 100, `pm-mips`, the `[bb-tick]` counters (expect: pm-entries ≈ INT 1Ch, paging-on = 0), the interrupt-context split, and the unsupported-function log (expect: empty).
6. **Regression.** The DOS 6.22 real-mode path and every existing `pj_fuzz` mode stay byte-identical to their baselines: the host is opt-in (`BB_DPMI=1`) until stage C is accepted, and `BB_DPMI=0` builds today's firmware.

## Staged plan

Five phases, each ending at a gate we can measure; the host stays opt-in until phase C's gate.

&#91;embedded content: roadmap · 5 phases, 4 gates\]

Phase 0 is useful on its own (the epoch fast path is worth \~9% of core 0 today) and fixes the two prerequisites every later phase needs: the exact function list, and the hook opcode working in protected mode. Phases A and B are delivered as the usual exact-install packages, each with its harness mode and mutations. The gate for C is numeric: ≥ 2.0 MIPS guest speed with sound and music on (2.67 without sound today, 0.60 with), with the `[bb-tick]` counters showing paging-on = 0 and the unsupported-function log empty.

## Risks and open questions

The largest risk is a client behaviour we have not seen because DOS/4GW has only ever run raw here; the census in phase 0 is the mitigation, and every unknown below has a cheap test.

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| DOS/4GW 1.97 needs a function outside stage A (0305h/0306h raw-switch addresses, 0A00h vendor API) | medium | census under a PC host first; unsupported calls logged with CF=1 so the first Pico run shows the gap |
| Ring 0 client: a program that relies on #GP for privileged instructions (CLI/STI trapping, IN/OUT) | low for Descent, medium for others | the emulator already runs the client at CPL 0 today; keep it, log privileged instructions in phase C and revisit per program |
| Virtual IF semantics: a handler that leaves interrupts disabled, or STI inside a handler, deadlocks or double-delivers | medium | the delivery and return stubs own IF; `[bb-tick]` shows delivered = EOIs; a watchdog logs a handler that does not return in 100 ms |
| HMI's handler assumes DOS/4GW's stack layout or chains to the previous vector with a `PUSH/RETF` into the kernel | low | the previous vector for an unhooked IRQ is a host stub that reflects to real mode; frames follow the DPMI layout, which HMI already sees under Windows |
| Real-mode callbacks needed by a driver we have not profiled (mouse, CD-ROM, network) | low for Descent | stage B slot design is ready; 16 slots |
| Linear-pool fragmentation at 4 MB guest RAM (DOS/4GW allocates, frees and resizes during level loads) | medium | resize-in-place when the next block is free, else move; log the largest free block at each level load |
| SRAM: delivery must stay out of SRAM; the hot entry is one call | low | enforced by `noinline` + section, checked by the heap verify |
| Timing: HMI expects its 120 Hz IRQ0 to be delivered promptly; a host that delays delivery to the end of a JIT run coalesces ticks | medium | delivery stays where `bb386_pmirq_poll` checks today (every slice); coalesced count is already in `[bb-tick]` |

Open questions to answer in phase 0:

- [ ] Which INT 31h functions DOS/4GW 1.97 actually calls when a host is present (census on a PC host).
- [ ] Whether `DOS16M` settings in Descent's environment disable DPMI detection.
- [ ] Whether HMI's drivers call 0303h (real-mode callbacks) for MIDI or digital initialisation.
- [ ] The hook opcode's behaviour in the 32-bit translator (decline vs trap) and its cost per trap.
- [ ] Whether the DOS 6.22 real-mode path needs a real INT 2Fh 1687h answer of "no host" for programs that must not see one (e.g. a VCPI check order).
