"""Stage 2A generated overlay: pre-LCD SD boot plus persistent A: write-through."""
from pathlib import Path

def _replace_once(s, old, new, label):
    if s.count(old) != 1:
        raise RuntimeError(f'Stage2A {label}: expected exactly one anchor, got {s.count(old)}')
    return s.replace(old, new, 1)

def apply(md: Path, root: Path):
    gen = root/'generated'/'bb_microdos_pico.c'
    cmake = md/'pico'/'CMakeLists.txt'
    src = gen.read_text(encoding='utf8')
    src = _replace_once(src,
        '    bb_lcd_console_init();',
        '    memset(g_guest,0,MD_GUEST_BYTES);\n'
        '    memcpy(g_disk,md_blob_disk,MD_DISK_BYTES);\n'
        '    if (bb_sd_boot_image(g_disk, MD_DISK_BYTES)) {\n'
        '        md_say("  disk-source: SD BOOT.IMG (pre-LCD, persistent writes)\\n");\n'
        '    } else {\n'
        '        memcpy(g_disk,md_blob_disk,MD_DISK_BYTES);\n'
        '        md_say("  disk-source: embedded fallback (volatile)\\n");\n'
        '    }\n'
        '    bb_lcd_console_init();', 'pre-LCD')
    src = _replace_once(src,
        '    memset(g_guest,0,MD_GUEST_BYTES); memcpy(g_disk,md_blob_disk,MD_DISK_BYTES);',
        '    /* guest/disk initialized before LCD */', 'disk init')
    src = _replace_once(src,
        '        memcpy(g_disk + off, data, size);',
        '        if (!bb_sd_persist_sector(sector, data, size)) return false;\n'
        '        memcpy(g_disk + off, data, size);', 'disk-write callback')
    src = src.replace('    md_say("  disk:    360 KiB image copied from flash to PSRAM (writes are lost at reset)\\n");',
                      '    md_say("  disk:    360 KiB in PSRAM (SD writes persist, fallback volatile)\\n");', 1)
    src = ('#include <stdbool.h>\n#include <stdint.h>\n#include <stddef.h>\n'
           'extern bool bb_sd_boot_image(uint8_t *, unsigned);\n'
           'extern bool bb_sd_persist_sector(uint32_t, const uint8_t *, size_t);\n' + src)
    gen.write_text(src, encoding='utf8')
    cm = cmake.read_text(encoding='utf8')
    begin='# === BB SD BOOT STAGE1 BEGIN ==='
    end='# === BB SD BOOT STAGE1 END ==='
    if begin in cm:
        if cm.count(begin) != 1 or cm.count(end) != 1: raise RuntimeError('Damaged SD CMake markers')
        cm=cm[:cm.index(begin)]+cm[cm.index(end)+len(end):]
    dep=(root.parent/'microconsole'/'third_party'/'pico-fatfs-sd').as_posix()
    block=f'''\n{begin}
set(BB_SD_LIB_ROOT "{dep}" CACHE PATH "microconsole pico-fatfs-sd checkout")
if(NOT EXISTS "${{BB_SD_LIB_ROOT}}/src/CMakeLists.txt")
    message(FATAL_ERROR "Stage2A requires pico-fatfs-sd at ${{BB_SD_LIB_ROOT}}")
endif()
if(NOT TARGET pico-fatfs-sd)
    add_subdirectory("${{BB_SD_LIB_ROOT}}/src" "${{CMAKE_CURRENT_BINARY_DIR}}/bb-pico-fatfs-sd")
endif()
target_sources(blitzbus_pico_b86_dos PRIVATE
    "{(root/'sd_boot'/'bb_sd_hw.c').as_posix()}"
    "{(root/'sd_boot'/'bb_sd_boot.c').as_posix()}")
target_link_libraries(blitzbus_pico_b86_dos PRIVATE pico-fatfs-sd hardware_spi)
set_source_files_properties("${{BB_SD_LIB_ROOT}}/src/src/crash.c"
    PROPERTIES HEADER_FILE_ONLY TRUE)
{end}
'''
    cmake.write_text(cm+block,encoding='utf8')
    print('[bb-sd] Stage2A persistence enabled; SD boot before LCD')

def disable(md: Path):
    cmake=md/'pico'/'CMakeLists.txt'
    cm=cmake.read_text(encoding='utf8')
    begin='# === BB SD BOOT STAGE1 BEGIN ==='
    end='# === BB SD BOOT STAGE1 END ==='
    if begin in cm:
        if cm.count(begin)!=1 or cm.count(end)!=1: raise RuntimeError('Malformed SD markers')
        cmake.write_text(cm[:cm.index(begin)]+cm[cm.index(end)+len(end):],encoding='utf8')
