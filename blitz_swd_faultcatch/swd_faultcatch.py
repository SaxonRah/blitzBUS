#!/usr/bin/env python3
"""Catch a HardFault live on the RP2350 with OpenOCD's vector catch.

Arms HardFault vector catch (cortex_m vector_catch hard_err) on both cores, resumes them, then waits.
When a core halts on HardFault entry it dumps: core registers, MSP/PSP,
HFSR/CFSR/MMFAR/BFAR/SFSR/SFAR, the 8-word exception frame at SP, and
memory around the stacked PC.  Read-only apart from DEMCR and halt/resume.

Usage (OpenOCD running with -f interface/cmsis-dap.cfg -f target/rp2350.cfg):
    python swd_faultcatch.py --out logs\\faultcatch.txt
then run 3DBENCH (and, to test the reflash hypothesis, `picotool reboot -f -u`).
"""
import argparse, re, socket, time, datetime

class OpenOCD:
    def __init__(self, host='127.0.0.1', port=6666):
        self.s = socket.create_connection((host, port), timeout=10); self.buf = bytearray()
    def call(self, cmd):
        self.s.sendall(cmd.encode() + b'\x1a')
        while b'\x1a' not in self.buf:
            chunk = self.s.recv(4096)
            if not chunk: raise ConnectionError('OpenOCD closed')
            self.buf.extend(chunk)
        i = self.buf.index(0x1a); out = bytes(self.buf[:i]).decode('utf-8', 'replace'); del self.buf[:i + 1]
        return out

CORES = ['rp2350.dap.core0', 'rp2350.dap.core1']
SCB = [('HFSR', 0xE000ED2C), ('CFSR', 0xE000ED28), ('MMFAR', 0xE000ED34), ('BFAR', 0xE000ED38),
       ('SFSR', 0xE000EDE4), ('SFAR', 0xE000EDE8), ('VTOR', 0xE000ED08), ('ICSR', 0xE000ED04)]

def rd32(o, core, addr):
    out = o.call(f'{core} mdw 0x{addr:08x}')
    m = re.search(r':\s*([0-9a-fA-F]{8})', out)
    return int(m.group(1), 16) if m else None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='faultcatch.txt')
    ap.add_argument('--host', default='127.0.0.1'); ap.add_argument('--port', type=int, default=6666)
    ap.add_argument('--code-dump', default='', help='also save the JIT code buffer to this .bin file')
    ap.add_argument('--code-base', default='0x20019040'); ap.add_argument('--code-end', default='0x20062040')
    a = ap.parse_args(); o = OpenOCD(a.host, a.port); log = open(a.out, 'a', encoding='utf-8')
    def w(s): print(s); log.write(s + '\n'); log.flush()
    w(f'=== faultcatch {datetime.datetime.now().isoformat()} ===')
    for c in CORES:
        o.call(f'{c} arp_halt'); o.call(f'{c} arp_waitstate halted 1000')
        w(f'{c}: ' + o.call(f'{c} cortex_m vector_catch hard_err').strip())   # DEMCR.VC_HARDERR
    for c in CORES: o.call(f'{c} resume')
    w('armed; waiting for a HardFault (Ctrl+C to stop)')
    try:
        while True:
            for c in CORES:
                st = o.call(f'{c} curstate').strip()
                if 'halted' not in st: continue
                w(f'\n### {c} HALTED (vector catch) at {datetime.datetime.now().isoformat()}')
                w(o.call(f'{c} reg'))
                for n, ad in SCB:
                    v = rd32(o, c, ad); w(f'{n:6s} = 0x{v:08x}' if v is not None else f'{n} = ?')
                regs = o.call(f'{c} reg sp')
                m = re.search(r'0x([0-9a-fA-F]+)', regs); sp = int(m.group(1), 16) if m else None
                if sp:
                    w(f'frame at sp=0x{sp:08x}:'); w(o.call(f'{c} mdw 0x{sp:08x} 8'))
                    pc = rd32(o, c, sp + 24)
                    lr = rd32(o, c, sp + 20)
                    w(f'stacked lr=0x{lr:08x}' if lr is not None else 'stacked lr=?')
                    if pc:
                        w(f'stacked pc=0x{pc:08x}; bytes around it:')
                        w(o.call(f'{c} mdb 0x{(pc & ~1) - 256:08x} 384'))
                    w('stack (64 words):'); w(o.call(f'{c} mdw 0x{sp:08x} 64'))
                if a.code_dump:
                    b0, b1 = int(a.code_base, 16), int(a.code_end, 16)
                    w(o.call(f'{c} dump_image {a.code_dump} 0x{b0:08x} 0x{b1 - b0:x}').strip())
                    w(f'code buffer 0x{b0:08x}..0x{b1:08x} saved to {a.code_dump}')
                w('core left halted for inspection (resume manually in telnet: resume)')
                return
            time.sleep(0.2)
    except KeyboardInterrupt:
        w('stopped')

if __name__ == '__main__':
    main()
