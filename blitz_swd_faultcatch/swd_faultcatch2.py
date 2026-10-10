#!/usr/bin/env python3
"""Catch a HardFault live on the RP2350 (v2).

OpenOCD must be running:  openocd -f interface/cmsis-dap.cfg -f target/rp2350.cfg
Arms DEMCR.VC_HARDERR on both cores, resumes them and waits.  A halt only
counts as a fault when DFSR.VCATCH is set; anything else is reported and
the core is resumed.  On a fault it dumps core registers, fault status, the
exception frame, code around the faulting PC and (optionally) the JIT code
buffer, then leaves the core halted.

Fixes over v1: OpenOCD 0.12 has no "<target> resume/reg/dump_image"
sub-commands, so v1's resume silently failed and the still-halted core was
reported as a fault.  v2 selects the target with "targets" and uses the
plain commands.
"""
import argparse, re, socket, time, datetime

class OpenOCD:
    def __init__(self, host='127.0.0.1', port=6666):
        self.s = socket.create_connection((host, port), timeout=60); self.buf = bytearray()
    def call(self, cmd):
        self.s.sendall(cmd.encode() + b'\x1a')
        while b'\x1a' not in self.buf:
            chunk = self.s.recv(65536)
            if not chunk: raise ConnectionError('OpenOCD closed')
            self.buf.extend(chunk)
        i = self.buf.index(0x1a); out = bytes(self.buf[:i]).decode('utf-8', 'replace'); del self.buf[:i + 1]
        return out

CORES = ['rp2350.dap.core0', 'rp2350.dap.core1']
SCB = [('HFSR', 0xE000ED2C), ('CFSR', 0xE000ED28), ('DFSR', 0xE000ED30), ('MMFAR', 0xE000ED34),
       ('BFAR', 0xE000ED38), ('SFSR', 0xE000EDE4), ('SFAR', 0xE000EDE8), ('VTOR', 0xE000ED08),
       ('ICSR', 0xE000ED04), ('SHCSR', 0xE000ED24)]
REGS = ['r0','r1','r2','r3','r4','r5','r6','r7','r8','r9','r10','r11','r12','sp','lr','pc','xpsr','msp','psp']

def rd32(o, core, addr):
    out = o.call(f'{core} mdw 0x{addr:08x}')
    m = re.search(r':\s*([0-9a-fA-F]{8})', out)
    return int(m.group(1), 16) if m else None

def regs(o, core):
    d, lines = {}, []
    for name in REGS:                                  # one at a time: an unknown name must not lose the rest
        out = o.call(f'{core} get_reg {name}')
        m = re.search(r'0x([0-9a-fA-F]+)', out)
        if m:
            d[name] = int(m.group(1), 16); lines.append(f'{name:5s} = 0x{d[name]:08x}')
        else:
            lines.append(f'{name:5s} = ? ({out.strip()[:60]})')
    return d, '\n'.join(lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='faultcatch.txt')
    ap.add_argument('--host', default='127.0.0.1'); ap.add_argument('--port', type=int, default=6666)
    ap.add_argument('--code-dump', default='')
    ap.add_argument('--code-base', default='0x20019040'); ap.add_argument('--code-end', default='0x20062040')
    ap.add_argument('--hot-dump', default='', help='also save the fast table + page table/codemap (r9 - 8 KiB .. +32 KiB)')
    a = ap.parse_args(); o = OpenOCD(a.host, a.port); log = open(a.out, 'a', encoding='utf-8')
    def w(s): print(s); log.write(s + '\n'); log.flush()
    w(f'=== faultcatch v2 {datetime.datetime.now().isoformat()} ===')
    for c in CORES:
        o.call(f'targets {c}'); o.call('halt 1000')
        o.call(f'{c} cortex_m vector_catch hard_err')
        o.call(f'{c} mww 0xE000ED30 0x1f')              # clear DFSR (write-1-to-clear)
    for c in CORES:
        o.call(f'targets {c}'); o.call('resume')
    time.sleep(0.3)
    for c in CORES:
        w(f'{c}: {o.call(f"{c} curstate").strip()}')
    w('armed; waiting for a HardFault (Ctrl+C to stop)')
    try:
        while True:
            for c in CORES:
                if 'halted' not in o.call(f'{c} curstate'): continue
                # OpenOCD clears DFSR when it notices the halt, so decide from the
                # exception number in IPSR instead (3 = HardFault)
                d, _ = regs(o, c)
                ipsr = d.get('xpsr', 0) & 0x1FF
                if ipsr != 3:
                    w(f'{c}: halted, IPSR={ipsr} (not HardFault), pc=0x{d.get("pc", 0):08x}; left halted, dumping anyway')
                w(f'\n### {c} HALTED on HardFault at {datetime.datetime.now().isoformat()}')
                d, raw = regs(o, c); w(raw.strip())
                for n, ad in SCB:
                    v = rd32(o, c, ad); w(f'{n:6s} = 0x{v:08x}' if v is not None else f'{n} = ?')
                lr = d.get('lr', 0)
                sp = d.get('psp') if (lr & 0x4) else d.get('msp')
                w(f'EXC_RETURN=0x{lr:08x} -> frame on {"PSP" if lr & 4 else "MSP"} at 0x{(sp or 0):08x}')
                if sp:
                    w(o.call(f'{c} mdw 0x{sp:08x} 8').strip())
                    spc = rd32(o, c, sp + 24); slr = rd32(o, c, sp + 20)
                    w(f'stacked pc=0x{(spc or 0):08x}  stacked lr=0x{(slr or 0):08x}')
                    if spc:
                        w('code around stacked pc (pc-256 .. pc+128):')
                        w(o.call(f'{c} mdb 0x{(spc & ~1) - 256:08x} 384').strip())
                    w('stack (64 words):'); w(o.call(f'{c} mdw 0x{sp:08x} 64').strip())
                if sp:
                    sip = rd32(o, c, sp + 16)                 # stacked r12 = nominal host address
                    r9 = d.get('r9', 0)
                    if sip is not None and r9:
                        idx = (sip >> 12) & 511
                        ent = rd32(o, c, r9 + idx * 4)
                        w(f'page-table check: stacked r12=0x{sip:08x} idx=0x{idx:03x} '
                          f'entry@0x{r9 + idx * 4:08x}=0x{(ent or 0):08x} -> translated 0x{(sip + (ent or 0)) & 0xffffffff:08x}')
                        w('page table (512 entries, nonzero only):')
                        for base in range(0, 512, 64):
                            words = o.call(f'{c} mdw 0x{r9 + base * 4:08x} 64')
                            vals = re.findall(r'\b([0-9a-fA-F]{8})\b(?!:)', words)
                            for k, v in enumerate(vals[:64]):
                                if int(v, 16): w(f'  pt[0x{base + k:03x}] = 0x{v}')
                    r8 = d.get('r8', 0)
                    if r8:
                        w('B86Cpu at r8 (256 words):'); w(o.call(f'{c} mdw 0x{r8:08x} 256').strip())
                if a.hot_dump and d.get('r9'):
                    h0 = d['r9'] - 0x2000
                    o.call(f'targets {c}')
                    w(o.call(f'dump_image {a.hot_dump} 0x{h0:08x} 0xa000').strip())
                    w(f'hot table 0x{h0:08x}..0x{h0 + 0xa000:08x} -> {a.hot_dump}')
                if a.code_dump:
                    b0, b1 = int(a.code_base, 16), int(a.code_end, 16)
                    o.call(f'targets {c}')
                    w(o.call(f'dump_image {a.code_dump} 0x{b0:08x} 0x{b1 - b0:x}').strip())
                    w(f'code buffer 0x{b0:08x}..0x{b1:08x} -> {a.code_dump}')
                w('core left halted (OpenOCD telnet: "targets rp2350.dap.core0; resume")')
                return
            time.sleep(0.2)
    except KeyboardInterrupt:
        w('stopped')

if __name__ == '__main__':
    main()
