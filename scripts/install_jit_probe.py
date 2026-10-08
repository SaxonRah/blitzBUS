"""Add a separate JIT execution target without modifying existing DOS targets."""
import argparse
from pathlib import Path

BEGIN = '# === blitzBUS v0.6 JIT PROBE BEGIN ==='
END = '# === blitzBUS v0.6 JIT PROBE END ==='

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--microdos', default=r'C:\microDOS')
    p.add_argument('--blitz86', default=r'C:\blitz86_v2')
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    cmake = Path(a.microdos) / 'pico' / 'CMakeLists.txt'
    probe = root / 'pico' / 'bb_jit_probe.c'
    b86 = Path(a.blitz86)
    if not cmake.is_file() or not probe.is_file() or not (b86/'src'/'be_t2.c').is_file():
        raise SystemExit('Missing microDOS Pico CMake, probe source, or blitz86 Thumb2 backend')
    text = cmake.read_text(encoding='utf-8')
    block = f'''\n{BEGIN}
# Standalone hardware gate: not connected to DOS runtime yet.
add_executable(blitzbus_b86_jit_probe
    "{probe.as_posix()}"
    "{(b86/'src'/'interp.c').as_posix()}"
    "{(b86/'src'/'jit.c').as_posix()}"
    "{(b86/'src'/'be_t2.c').as_posix()}")
target_include_directories(blitzbus_b86_jit_probe PRIVATE "{(b86/'include').as_posix()}")
# Bounded metadata footprint, independent of the benchmark's JIT configuration.
target_compile_definitions(blitzbus_b86_jit_probe PRIVATE
    B86_MAXB=256 B86_MAP_BITS=10 MICRODOS_PICO_SYS_KHZ=300000)
md_pico_common(blitzbus_b86_jit_probe 0)
pico_set_program_name(blitzbus_b86_jit_probe "blitzBUS Thumb2 JIT proof")
{END}
'''
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(END) < text.index(BEGIN):
            raise SystemExit('Existing v0.6 markers damaged; CMake left unchanged')
        start = text.index(BEGIN)
        end = text.index(END) + len(END)
        text = text[:start] + block.strip('\n') + text[end:]
    else:
        text += block
    cmake.write_text(text, encoding='utf-8')
    print('[blitzBUS] Installed isolated blitz86 Thumb2 JIT probe target')
    print('[blitzBUS] Existing DOS/LCD firmware target unchanged')

if __name__ == '__main__':
    main()
