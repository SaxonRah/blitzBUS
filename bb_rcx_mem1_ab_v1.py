#!/usr/bin/env python3
r"""blitz86 Thumb-2 memory RCL/RCR by 1: reversible A/B experiment.

This modifies ONE complete source file, C:\blitz86_v2\src\jit.c, without
using git patches.  The original bytes are backed up and restored exactly.
It preserves eager dead-stub unchaining and is INCOMPATIBLE with installed
form/lookup audit files (restore the latter first).

Windows, in C:\blitzBUS:
    python bb_rcx_mem1_ab_v1.py selftest
    python bb_rcx_mem1_ab_v1.py probe
    python bb_rcx_mem1_ab_v1.py apply   # installs OFF control
    python bb_rcx_mem1_ab_v1.py set on
    python bb_rcx_mem1_ab_v1.py verify
    # rebuild, run T2ECPU, 3DBENCH, exercise memory RCL/RCR
    python bb_rcx_mem1_ab_v1.py set off
    # rebuild, run control
    python bb_rcx_mem1_ab_v1.py restore  # restores byte-for-byte original

Experimental firmware change. Do NOT treat software-only tests as Pico proof.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path(r'C:\blitz86_v2\src\jit.c') if sys.platform == 'win32' else ROOT / '_fixture_blitz86_v2' / 'src' / 'jit.c'
BACKUP = SOURCE.with_name('jit.c.bb-rcx-mem1-ab-original.bak')
MANIFEST = ROOT / 'bb_rcx_mem1_ab_manifest.json'
MARK = 'BB_RCX_MEM1_AB_V1'
TOGGLE = re.compile(r'(?m)^(#define[ \t]+B86_RCX_MEM1[ \t]+)([01])(?=\r?$)')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def exactly_one(src: str, anchor: str, name: str) -> None:
    n = src.count(anchor)
    if n != 1:
        raise RuntimeError(f'{name}: expected one anchor, found {n}; NO changes made')


def change(original: bytes, enabled: bool) -> bytes:
    bom = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    content = original[len(bom):].decode('utf-8')
    nl = '\r\n' if '\r\n' in content else '\n'
    normalized = content.replace('\r\n', '\n')
    if MARK in normalized:
        raise RuntimeError('Already installed; use verify/set/restore, not apply')
    for alien in ('BB_THUMB2_FORM_LOOKUP_AUDIT_V1', 'BB_AUDIT_SRAM_FLASH_FIX_V1',
                  'BB_FALLBACK_OPCODE_PROFILE_V1', 'BB_INT_VECTOR_PROFILE_V1'):
        if alien in normalized:
            raise RuntimeError(f'Prior diagnostic ({alien}) still installed. Restore it first.')

    macro = '#define PLOGN 4096u'
    exactly_one(normalized, macro, 'JIT macro')
    normalized = normalized.replace(macro,
        '/* BB_RCX_MEM1_AB_V1: Thumb-2 8/16-bit RCL/RCR memory, count=1. */\n'
        f'#define B86_RCX_MEM1 {int(enabled)}\n' + macro, 1)

    # Keep register rotate handling and all other shift classifications untouched.
    original_cls = '''        d->native = (d->reg == 4 || d->reg == 5 || d->reg == 7) ||
                    (d->reg < 4 && d->mod == 3 && (d->w || d->rm < 4));   /* ROL/ROR/RCL/RCR r,1 */'''
    modified_cls = '''        d->native = (d->reg == 4 || d->reg == 5 || d->reg == 7) ||
                    (B86_RCX_MEM1 && memop && (d->reg == 2 || d->reg == 3)) ||
                    (d->reg < 4 && d->mod == 3 && (d->w || d->rm < 4));   /* ROL/ROR/RCL/RCR r,1 */'''
    exactly_one(normalized, original_cls, 'D0/D1 classification')
    normalized = normalized.replace(original_cls, modified_cls, 1)

    materialize = '    if (is_rcx(d)) return 1;   /* defines only CF/OF: older ZF/SF records must not be deferred past it */'
    exactly_one(normalized, materialize, 'lazy materialization')
    normalized = normalized.replace(materialize,
        '''#if B86_RCX_MEM1
    /* Memory RCL/RCR will materialize the previous arithmetic/overlay flags.
       Do not postpone an older ZF/SF record beyond this instruction. */
    if ((op == 0xD0 || op == 0xD1) && d->mod != 3 &&
        (d->reg == 2 || d->reg == 3)) return 1;
#endif
''' + materialize, 1)

    lowered = '''#if B86_RCX_MEM1
        /* BB_RCX_MEM1_AB_V1: memory RCL/RCR by one (D0 byte / D1 word).
           Two Thumb-2 virtual temporaries: T0=effective address, T1=value.
           Preserve existing 8086 flags: these rotates define CF and OF
           only; ZF/SF/PF/AF must not be overwritten by the ARM operation.
           We deliberately do NOT fuse NZCV across the checked memory store. */
        if ((d->reg == 2 || d->reg == 3) && d->mod != 3) {
            const unsigned bits = w ? 16u : 8u;
            const unsigned pad = 32u - bits;
            /* Fold any earlier lazy ZF/SF/PF/CF records BEFORE updating the
               CF/OF bits; otherwise a later materialization could undo them. */
            flags_if_lazy(t, d, 1);
            t->inc_pending = 0;
            ea_modrm(t, d);
            if (d->lazy) be_stctx(e, V_T0, OFF(rep_tmp[0]));
            /* host C = incoming x86 CF; LDRH/LDRB and MOV/shift (S=0)
               preserve it, so a third Thumb-2 scratch is unnecessary. */
            be_set_c_cf(e, V_T1, 0);
            be_load(e, w, V_T1, V_T0);
            if (d->reg == 2) {        /* RCL a,1 = (a << 1) + CF */
                be_adcsbc(e, 0, V_T1, V_T1, V_T1);
            } else {                  /* RCR a,1: RRX in top bits */
                if (d->lazy) be_stctx(e, V_T1, OFF(scratch)); /* old bit0 -> CF */
                be_lsl(e, V_T1, V_T1, pad);
                /* Thumb-2 MOV.W, RRX; type 3 / shift 0 is the RRX encoding. */
                be_shift_imm(e, 3, V_T1, V_T1, 0);
                be_lsr(e, V_T1, V_T1, pad);
            }
            if (d->lazy) {
                /* SMC can exit immediately after be_store(), so materialize
                   the NEW CF/OF BEFORE the checked store, not after it. */
                be_stctx(e, V_T1, OFF(rep_tmp[1]));  /* resulting 8/16 bits */
                if (d->reg == 2) {        /* RCL: CF = bit[bits] of 2*a+CF */
                    be_ubfx(e, V_T0, V_T1, bits, 1);
                    be_ubfx(e, V_T1, V_T1, bits - 1u, 1);
                    be_op(e, AOP_EOR, V_T1, V_T1, V_T0); /* OF = MSB ^ CF */
                    be_op_lsl(e, AOP_ORR, V_T0, V_T0, V_T1, 11);
                } else {                   /* RCR: CF=old bit0, OF=new top2 XOR */
                    be_op_lsl(e, AOP_EOR, V_T0, V_T1, V_T1, 1);
                    be_ubfx(e, V_T0, V_T0, bits - 1u, 1); /* OF */
                    be_ldctx(e, V_T1, OFF(scratch));
                    be_ubfx(e, V_T1, V_T1, 0, 1); /* CF */
                    be_op_lsl(e, AOP_ORR, V_T0, V_T1, V_T0, 11);
                }
                be_ldctx(e, V_T1, OFF(flags));
                be_opi(e, AOP_AND, V_T1, V_T1,
                       (uint16_t)~(B86_CF | B86_OF));
                be_op(e, AOP_ORR, V_T1, V_T1, V_T0);
                be_stctx(e, V_T1, OFF(flags));
                be_ldctx(e, V_T0, OFF(rep_tmp[0]));
                be_ldctx(e, V_T1, OFF(rep_tmp[1]));
            }
            be_store(e, w, V_T1, V_T0, 1, d->next);
            return 1;
        }
#endif
'''
    anchor = '    case 0xD0: case 0xD1:\n        if (is_rcx(d)) {'
    exactly_one(normalized, anchor, 'rotate lowerer')
    normalized = normalized.replace(anchor, '    case 0xD0: case 0xD1:\n' + lowered + '        if (is_rcx(d)) {', 1)
    out = normalized.replace('\n', nl).encode('utf-8')
    return bom + out


def expect_manifest():
    if not MANIFEST.is_file():
        raise RuntimeError('No experiment manifest. Run apply after probe.')
    man = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if man.get('marker') != MARK or man.get('source') != str(SOURCE) or man.get('backup') != str(BACKUP):
        raise RuntimeError('Manifest does not identify this experiment/source')
    if not BACKUP.is_file() or digest(BACKUP.read_bytes()) != man['original_sha']:
        raise RuntimeError('Original source backup missing or changed; refusing')
    return man, BACKUP.read_bytes()


def expected(original, on):
    return change(original, on)


def get_state():
    man, orig = expect_manifest()
    if not SOURCE.is_file(): raise RuntimeError('Edited source missing')
    now = SOURCE.read_bytes()
    if now == expected(orig, False): mode = 'OFF'
    elif now == expected(orig, True): mode = 'ON'
    else: raise RuntimeError('Source changed outside this controller. Keep backup; reconcile edits before toggling/restoring.')
    return man, orig, mode


def selftest():
    # Independent x86 RCL/RCR reference vs emitter algebra, every byte/word
    # operand and each carry input.  No hardware claims.
    cases = 0
    for bits in (8, 16):
        mask = (1 << bits) - 1
        for a in range(mask+1):
            for cf in (0, 1):
                # RCL: generated ADC(v,v)+CF retains outgoing carry in bit bits.
                x = (a * 2 + cf)
                r = x & mask
                cfout = (x >> bits) & 1
                of = ((x >> (bits-1)) ^ cfout) & 1
                ref_r = ((a << 1) | cf) & mask
                ref_cf = (a >> (bits-1)) & 1
                ref_of = ((ref_r >> (bits-1)) ^ ref_cf) & 1
                assert (r,cfout,of) == (ref_r,ref_cf,ref_of)
                # RCR: generated (RRX(a<<pad) >> pad).
                pad = 32 - bits
                rrx = ((cf << 31) | ((a << pad) >> 1)) & 0xFFFFFFFF
                r = (rrx >> pad) & mask
                cfout = a & 1
                of = ((r >> (bits-1)) ^ (r >> (bits-2))) & 1
                ref_r = ((a >> 1) | (cf << (bits-1))) & mask
                ref_cf = a & 1
                ref_of = (cf ^ ((a >> (bits-1)) & 1)) & 1
                assert (r,cfout,of) == (ref_r,ref_cf,ref_of)
                cases += 2
    print(f'SELFTEST PASS: {cases:,} byte/word rotate cases, both CF values; no Pico execution')


def do(command, mode=None):
    if command == 'selftest': selftest(); return
    if command == 'probe':
        if MANIFEST.exists() or BACKUP.exists():
            _,_,state = get_state(); print(f'EXISTING experiment {state}; use verify/set/restore'); return
        if not SOURCE.exists(): raise RuntimeError(f'Not found: {SOURCE}')
        orig = SOURCE.read_bytes()
        for on in (False,True):
            proposed = change(orig,on)
            print(f'PROBE {"ON" if on else "OFF"}: original={len(orig)} B changed={len(proposed)-len(orig):+d} B; valid source anchors')
        return
    if command == 'apply':
        if MANIFEST.exists() or BACKUP.exists():
            raise RuntimeError('A backup or manifest already exists: no duplicate application. Use verify.')
        if not SOURCE.is_file(): raise RuntimeError(f'Missing source: {SOURCE}')
        orig = SOURCE.read_bytes()
        off=change(orig,False); on=change(orig,True)
        if off == on: raise RuntimeError('Toggle failed: ON/OFF identical')
        BACKUP.write_bytes(orig)
        MANIFEST.write_text(json.dumps({'marker':MARK,'source':str(SOURCE),'backup':str(BACKUP),
                                         'original_sha':digest(orig),'off_sha':digest(off),'on_sha':digest(on)},indent=2), encoding='utf-8')
        SOURCE.write_bytes(off)
        print('Installed with RCL/RCR memory OFF (control). Original source preserved.')
    elif command == 'verify':
        _,_,state = get_state()
        print(f'VERIFIED: memory RCL/RCR {state}; byte-identical original backup intact')
    elif command == 'set':
        _,orig,state = get_state()
        desired = 'ON' if mode == 'on' else 'OFF'
        if state == desired: print(f'Already {state}; nothing changed'); return
        SOURCE.write_bytes(expected(orig, mode=='on'))
        _,_,check = get_state()
        print(f'Set memory RCL/RCR {check}. Rebuild and flash firmware before testing.')
    elif command == 'restore':
        _,orig,state = get_state()
        SOURCE.write_bytes(orig)
        if SOURCE.read_bytes() != orig: raise RuntimeError('Restore write verification failed')
        MANIFEST.unlink(); BACKUP.unlink()
        print(f'Restored exact original source bytes (previous state: {state}); eager unchaining retained.')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['selftest','probe','apply','verify','set','restore'])
    ap.add_argument('mode',nargs='?',choices=['on','off'])
    args=ap.parse_args()
    if args.command == 'set' and args.mode is None: ap.error('set requires on or off')
    if args.command != 'set' and args.mode is not None: ap.error('mode is only valid for set')
    try: do(args.command,args.mode)
    except (RuntimeError,ValueError,UnicodeDecodeError,AssertionError,OSError) as e:
        print(f'ERROR: {e}',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
