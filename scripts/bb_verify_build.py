#!/usr/bin/env python3
"""BB_BUILD_GUARD_V1: prove the firmware is compiled with the settings you chose.

  python bb_verify_build.py --microdos C:\\microDOS --blitzbus C:\\blitzBUS

scripts/install_live.py writes every definition of the blitzbus_pico_b86_dos
target to generated/bb_expected_defines.txt. This script reads the compile
commands the build system will actually run for that target (build.ninja, or
flags.make for Makefile generators) and checks that each definition is there
with the same value. Exit 0 = match, 1 = mismatch, 2 = could not check.

It exists because a build directory with CMAKE_SUPPRESS_REGENERATION=ON (and a
CMakeLists.txt that could no longer generate) silently kept compiling with
flags from an old configure: settings in bb.config.psd1 never reached the
firmware, for hours, without any error.
"""
import argparse, os, pathlib, re, struct, sys

TARGET = "blitzbus_pico_b86_dos"


def defines_from_ninja(text):
    """-D tokens of the target's C objects (all objects of one target share them)."""
    found = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("build CMakeFiles/%s.dir/" % TARGET) and ".c.obj:" in line.split(" ", 2)[1]:
            for follow in lines[i + 1:i + 12]:
                if not follow.startswith("  "):
                    break
                s = follow.strip()
                if s.startswith("DEFINES = "):
                    found.append(s[len("DEFINES = "):])
            if found:
                break
    return found[0] if found else None


def defines_from_flags_make(build):
    p = build / "CMakeFiles" / ("%s.dir" % TARGET) / "flags.make"
    if not p.is_file():
        return None
    for line in p.read_text(errors="replace").splitlines():
        if line.startswith("C_DEFINES = "):
            return line[len("C_DEFINES = "):]
    return None


def elf_symbols(path, names):
    """BB_HEAP_GUARD_V1: values of the named symbols in a little-endian ELF32 file."""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        return None
    e_shoff, = struct.unpack_from("<I", data, 0x20)
    e_shentsize, e_shnum = struct.unpack_from("<HH", data, 0x2E)
    secs = [struct.unpack_from("<IIIIIIIIII", data, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    out = {}
    for _name, typ, _flags, _addr, offset, size, link, _info, _align, _entsize in secs:
        if typ != 2:                                   # SHT_SYMTAB
            continue
        stro = secs[link][4]
        for k in range(size // 16):
            st_name, st_value = struct.unpack_from("<II", data, offset + 16 * k)
            if not st_name:
                continue
            end = data.index(b"\0", stro + st_name)
            nm = data[stro + st_name:end].decode("ascii", "replace")
            if nm in names:
                out[nm] = st_value
    return out


def check_heap(elf):
    """BB_HEAP_GUARD_V1: refuse firmware whose SRAM heap is too small. The
    heap is whatever SRAM is left after .data/.bss; the real-mode JIT and FatFS
    allocate from it at boot, and running out panics the Pico ('Out of memory')
    before DOS starts. 3,788 bytes panicked, 4,180 booted (2026-11-01)."""
    minimum = int(os.environ.get("BB_MIN_HEAP", "6144"))
    if not elf.is_file():
        print("[bb-verify] heap: WARNING, cannot check (%s missing)" % elf)
        return 0
    sym = elf_symbols(elf, {"__end__", "__HeapLimit"})
    if not sym or "__end__" not in sym or "__HeapLimit" not in sym:
        print("[bb-verify] heap: WARNING, cannot check (__end__/__HeapLimit not in %s)" % elf.name)
        return 0
    heap = sym["__HeapLimit"] - sym["__end__"]
    if heap < minimum:
        print("[bb-verify] HEAP TOO SMALL: %d bytes of SRAM heap, minimum %d (BB_MIN_HEAP)." % (heap, minimum))
        print("   The Pico would panic 'Out of memory' at boot. Free SRAM, for example")
        print("   BB_PJ_HOT_KB 4 or 8 lower (each KiB of hot tier = 1 KiB of heap).")
        return 1
    print("[bb-verify] heap OK: %d bytes of SRAM heap (minimum %d)" % (heap, minimum))
    return 0


def parse(defines):
    out = {}
    for m in re.finditer(r"-D([A-Za-z_][A-Za-z0-9_]*)(?:=(\S*))?", defines):
        out[m.group(1)] = m.group(2) if m.group(2) is not None else "1"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--microdos", required=True)
    ap.add_argument("--blitzbus", required=True)
    a = ap.parse_args()
    build = pathlib.Path(a.microdos) / "build-pico" / "out"
    exp_file = pathlib.Path(a.blitzbus) / "generated" / "bb_expected_defines.txt"
    if not exp_file.is_file():
        print("[bb-verify] CANNOT CHECK: %s missing (scripts/install_live.py writes it)" % exp_file)
        return 2
    expected = {}
    for tok in exp_file.read_text().split():
        name, _, value = tok.partition("=")
        expected[name] = value if _ else "1"
    ninja = build / "build.ninja"
    defines = defines_from_ninja(ninja.read_text(errors="replace")) if ninja.is_file() else None
    if defines is None:
        defines = defines_from_flags_make(build)
    if defines is None:
        print("[bb-verify] CANNOT CHECK: no compile definitions for %s found in %s" % (TARGET, build))
        return 2
    actual = parse(defines)
    missing = [n for n in expected if n not in actual]
    differ = [(n, expected[n], actual[n]) for n in expected if n in actual and actual[n] != expected[n]]
    if missing or differ:
        print("[bb-verify] MISMATCH: the firmware would NOT be built with your settings.")
        for n in missing[:20]:
            print("   missing   %s=%s" % (n, expected[n]))
        for n, e, v in differ[:20]:
            print("   different %s: wanted %s, build uses %s" % (n, e, v))
        print("   Fix: cmake -DCMAKE_SUPPRESS_REGENERATION=OFF %s   (then look for 'CMake Error' lines)" % build)
        return 1
    print("[bb-verify] OK: all %d definitions from install_live.py are in the build (%s)" %
          (len(expected), "build.ninja" if ninja.is_file() else "flags.make"))
    return check_heap(build / (TARGET + ".elf"))


if __name__ == "__main__":
    sys.exit(main())
