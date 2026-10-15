cmake_minimum_required(VERSION 3.16)

# WINFIX2: Ninja repeatedly regenerated build.ninja 100 times in the Windows
# standalone build, never reaching compilation. This project is ALWAYS
# explicitly configured by build.ps1, so no automatic regeneration is needed.
# Does not modify any external SDK or microDOS/blitz86 source.
set(CMAKE_SUPPRESS_REGENERATION ON CACHE BOOL
    "Standalone V3: explicitly configure, do not loop on Ninja regen" FORCE)

# WINFIX1: a standalone Pico 2 target.  The former vscode.cmake helper
# requires a vscode-specific environment and causes /.pico-sdk/sdk resolution
# when invoked from a normal PowerShell console.  Do NOT include that helper.
# build.ps1 supplies the verified full PICO_SDK_PATH and a Ninja generator.
if(NOT CMAKE_GENERATOR STREQUAL "Ninja")
    message(FATAL_ERROR "This isolated RP2350 build requires -G Ninja (run build.ps1)")
endif()
if(NOT PICO_SDK_PATH)
    message(FATAL_ERROR "PICO_SDK_PATH must point to pico_sdk_init.cmake (run build.ps1)")
endif()
if(NOT EXISTS "${PICO_SDK_PATH}/pico_sdk_init.cmake")
    message(FATAL_ERROR "PICO_SDK_PATH invalid: ${PICO_SDK_PATH}")
endif()

set(PICO_BOARD pimoroni_pico_plus2_rp2350 CACHE STRING "Board")
set(MD_ROOT "C:/microDOS" CACHE PATH "microDOS root, for existing SDK import and Pico allocator")
set(BLITZ86_ROOT "C:/blitz86_v2" CACHE PATH "Existing blitz86 source (read-only)")
if(NOT EXISTS "${MD_ROOT}/pico/pico_sdk_import.cmake")
    message(FATAL_ERROR "microDOS Pico SDK import not found: ${MD_ROOT}")
endif()
if(NOT EXISTS "${MD_ROOT}/pico/b86_hw_alloc.c")
    message(FATAL_ERROR "microDOS Pico JIT allocation helper not found")
endif()
if(NOT EXISTS "${BLITZ86_ROOT}/src/be_t2.c")
    message(FATAL_ERROR "blitz86 Thumb-2 sources not found")
endif()

include("${MD_ROOT}/pico/pico_sdk_import.cmake")
project(bb_irq0_pico_v3 C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_EXTENSIONS ON)
pico_sdk_init()

# Match the critical production flags across jit.c and be_t2.c.
set(BB_V3_DEFS
    B86_MAXB=2048 B86_MAP_BITS=12 B86_FAST_BITS=10
    B86_PAGED=1 B86_OPT_PAGE_ZERO=1 B86_EA_IMM12_FAST=1
    B86_OPT_CS_CONST=0
)
add_library(bb_irq0_jit_core OBJECT "${BLITZ86_ROOT}/src/jit.c")
target_include_directories(bb_irq0_jit_core PRIVATE
    "${BLITZ86_ROOT}/include" "${MD_ROOT}/pico")
target_compile_definitions(bb_irq0_jit_core PRIVATE
    ${BB_V3_DEFS}
    B86_HW_PICO=1
    calloc=b86_hw_calloc
    free=b86_hw_free)
target_compile_options(bb_irq0_jit_core PRIVATE
    -O2 -include "${MD_ROOT}/pico/b86_hw_alloc.h")

add_executable(bb_irq0_pico_v3
    "${CMAKE_CURRENT_SOURCE_DIR}/bb_irq0_pico_v3.c"
    "${MD_ROOT}/pico/b86_hw_alloc.c"
    "${BLITZ86_ROOT}/src/interp.c"
    "${BLITZ86_ROOT}/src/be_t2.c")
target_include_directories(bb_irq0_pico_v3 PRIVATE
    "${BLITZ86_ROOT}/include" "${MD_ROOT}/pico")
target_compile_definitions(bb_irq0_pico_v3 PRIVATE ${BB_V3_DEFS} B86_HW_PICO=1)
target_compile_options(bb_irq0_pico_v3 PRIVATE -O2 -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(bb_irq0_pico_v3 PRIVATE
    bb_irq0_jit_core pico_stdlib hardware_psram hardware_clocks)
pico_enable_stdio_usb(bb_irq0_pico_v3 1)
pico_enable_stdio_uart(bb_irq0_pico_v3 0)
pico_add_extra_outputs(bb_irq0_pico_v3)
target_link_options(bb_irq0_pico_v3 PRIVATE
    "-Wl,--print-memory-usage"
    "-Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/bb_irq0_pico_v3.map")
pico_set_program_name(bb_irq0_pico_v3 "blitzBUS IRQ0 V3 native Thumb-2 differential")
