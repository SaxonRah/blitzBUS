"""Idempotent generated-source SD overlay, called from install_live.py."""
from pathlib import Path

def apply(md: Path, root: Path):
    gen= root/'generated'/'bb_microdos_pico.c'
    cmake=md/'pico'/'CMakeLists.txt'
    src=gen.read_text(encoding='utf8')
    # Preload before bb_lcd_console_init() changes clk_peri to 150 MHz.
    # The flash image is copied first so any failed / partial SD load falls
    # back to a clean in-memory embedded disk, even on read failure.
    lcd_anchor='    bb_lcd_console_init();'
    disk_anchor='    memset(g_guest,0,MD_GUEST_BYTES); memcpy(g_disk,md_blob_disk,MD_DISK_BYTES);'
    if src.count(lcd_anchor)!=1 or src.count(disk_anchor)!=1:
        raise RuntimeError('SD pre-LCD overlay: source anchors changed; not modifying')
    if src.index(lcd_anchor)>src.index(disk_anchor):
        raise RuntimeError('SD pre-LCD overlay: unexpected startup order')
    src=src.replace(lcd_anchor,
        '    memset(g_guest,0,MD_GUEST_BYTES);\n'
        '    memcpy(g_disk,md_blob_disk,MD_DISK_BYTES);\n'
        '    if (bb_sd_boot_image(g_disk, MD_DISK_BYTES)) {\n'
        '        md_say("  disk-source: SD BOOT.IMG (pre-LCD)\\n");\n'
        '    } else {\n'
        '        memcpy(g_disk,md_blob_disk,MD_DISK_BYTES);\n'
        '        md_say("  disk-source: embedded fallback (pre-LCD)\\n");\n'
        '    }\n' + lcd_anchor, 1)
    src=src.replace(disk_anchor,'    /* Disk and guest initialized before the LCD to isolate SD SPI timing. */',1)
    # Correct the original disk-source line, which otherwise misleadingly
    # states that flash was selected even after a successful SD preload.
    src=src.replace('    md_say("  disk:    360 KiB image copied from flash to PSRAM (writes are lost at reset)\\n");',
                    '    md_say("  disk:    360 KiB in PSRAM (writes are lost at reset)\\n");',1)
    head='#include <stdbool.h>\n#include <stdint.h>\nextern bool bb_sd_boot_image(uint8_t *, unsigned);\n'
    src=head+src
    gen.write_text(src,encoding='utf8')
    cm=cmake.read_text(encoding='utf8')
    begin='# === BB SD BOOT STAGE1 BEGIN ==='
    end='# === BB SD BOOT STAGE1 END ==='
    if begin in cm:
        if cm.count(begin)!=1 or cm.count(end)!=1:raise RuntimeError('SD overlay: damaged CMake markers')
        cm=cm[:cm.index(begin)]+cm[cm.index(end)+len(end):]
    dep=(root.parent/'microconsole'/'third_party'/'pico-fatfs-sd').as_posix()
    block=f'''\n{begin}
set(BB_SD_LIB_ROOT "{dep}" CACHE PATH "microconsole pico-fatfs-sd checkout")
if(NOT EXISTS "${{BB_SD_LIB_ROOT}}/src/CMakeLists.txt")
    message(FATAL_ERROR "SD stage1 requires pico-fatfs-sd at ${{BB_SD_LIB_ROOT}}; see README")
endif()
if(NOT TARGET pico-fatfs-sd)
    add_subdirectory("${{BB_SD_LIB_ROOT}}/src" "${{CMAKE_CURRENT_BINARY_DIR}}/bb-pico-fatfs-sd")
endif()
target_sources(blitzbus_pico_b86_dos PRIVATE
    "{(root/'sd_boot'/'bb_sd_hw.c').as_posix()}"
    "{(root/'sd_boot'/'bb_sd_boot.c').as_posix()}")
target_link_libraries(blitzbus_pico_b86_dos PRIVATE pico-fatfs-sd hardware_spi)
# Both projects define HardFault_Handler. Keep the blitzBUS handler with its
# watchdog scratch diagnostics; do not compile the SD library crash handler
# into this executable. HEADER_FILE_ONLY suppresses its INTERFACE_SOURCES
# compilation without changing files in the shared microconsole checkout.
set_source_files_properties("${{BB_SD_LIB_ROOT}}/src/src/crash.c"
    PROPERTIES HEADER_FILE_ONLY TRUE)
{end}
'''
    # CMake target already exists; remove a prior SD block on regeneration.
    if begin in cm:
        if cm.count(begin)!=1 or cm.count(end)!=1: raise RuntimeError('SD overlay: duplicate/damaged CMake section')
        cm=cm[:cm.index(begin)]+cm[cm.index(end)+len(end):]
    cmake.write_text(cm+block,encoding='utf8')
    print('[bb-sd] Stage1 SD boot overlay installed (SPI1 GP12/13/14/15)')


def disable(md: Path):
    cmake=md/'pico'/'CMakeLists.txt'
    cm=cmake.read_text(encoding='utf8')
    begin='# === BB SD BOOT STAGE1 BEGIN ==='
    end='# === BB SD BOOT STAGE1 END ==='
    if begin in cm:
        if cm.count(begin)!=1 or cm.count(end)!=1: raise RuntimeError('SD overlay: malformed markers')
        cm=cm[:cm.index(begin)]+cm[cm.index(end)+len(end):]
        cmake.write_text(cm,encoding='utf8')
