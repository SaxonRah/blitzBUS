"""Install isolated live DOS/JIT proof target. Does not edit original C source."""
import argparse
import os
from pathlib import Path

BEGIN = '# === blitzBUS v0.7 LIVE DOS BEGIN ==='
END = '# === blitzBUS v0.7 LIVE DOS END ==='

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--microdos',default=r'C:\microDOS')
    p.add_argument('--blitz86',default=r'C:\blitz86_v2')
    a=p.parse_args()
    lcd_hz=os.environ.get("BB_LCD_SPI_HZ","40000000")
    lcd_lace=os.environ.get("BB_LCD_LACE","0")
    if lcd_lace not in ("0","1"):
        raise SystemExit("BB_LCD_LACE must be 0 (full) or 1 (alternating rows)")
    lcd_peri=os.environ.get("BB_LCD_PERI_HZ","150000000")
    # BB_EVICTION_AB_V1: compiler parameters, no runtime overhead.
    eviction_chunk=int(os.environ.get('BB_EVICT_CHUNK','4096'))
    eviction_room=int(os.environ.get('BB_EVICT_ROOM','2048'))
    if eviction_chunk not in (2048,4096,8192):
        raise SystemExit('BB_EVICT_CHUNK must be 2048,4096,8192')
    if eviction_room not in (2048,4096):
        raise SystemExit('BB_EVICT_ROOM must be 2048,4096')
    # BB_CHAIN_AUDIT_V1: test the existing chain mechanism, do not change its logic.
    no_chain=os.environ.get("BB_NO_CHAIN","0")
    if no_chain not in ("0","1"):
        raise SystemExit("BB_NO_CHAIN must be 0 or 1")
    hot=os.environ.get("BB_HOT_THRESHOLD","32")   # 32
    if not hot.isdigit() or int(hot)>255:
        raise SystemExit("BB_HOT_THRESHOLD must be 0..255 (0 = translate at once)")
    # B86_386_NATIVE_T1_V1: experimental 386 real-mode JIT, OFF by default.
    native386=os.environ.get('BB_386_NATIVE_T1','0')
    if native386 not in ('0','1'):
        raise SystemExit('BB_386_NATIVE_T1 must be 0 or 1')
    if native386=='1' and os.environ.get('BB_CPU','8086')!='386':
        raise SystemExit('BB_386_NATIVE_T1=1 requires BB_CPU=386')
    cpu=os.environ.get("BB_CPU","8086")       # v63: 8086 (exact), 186; v64: 286 (real mode)
    if cpu not in ("8086","186","286","386"):
        raise SystemExit("BB_CPU must be 8086, 186, 286 or 386")
    cpu_model={"8086":0,"186":1,"286":2,"386":3}[cpu]
    paged=os.environ.get("BB_PAGED","1")
    if paged not in ("0","1"):
        raise SystemExit("BB_PAGED must be 0 or 1 (v40 SRAM-backed guest pages)")
    bbuf=os.environ.get("BB_BBUF","1")
    pc_prof=os.environ.get("BB_PC_PROFILE","0")
    miss_prof=os.environ.get("BB_MISS_PROFILE","0")
    if miss_prof not in ("0","1"):
        raise SystemExit("BB_MISS_PROFILE must be 0 or 1 (per-category cache-miss profile)")
    mprof_defs=" B86_MPROF=1 B86_XACCESS=bb_xip_accesses BB_MISS_PROFILE=1" if miss_prof=="1" else ""
    if pc_prof not in ("0","1"):
        raise SystemExit("BB_PC_PROFILE must be 0 or 1 (500 Hz PC sampler)")
    tv_sram=os.environ.get("BB_TV_SRAM","0")
    if tv_sram not in ("0","1"):
        raise SystemExit("BB_TV_SRAM must be 0 or 1 (r52b translator scratch in SRAM)")
    if bbuf not in ("0","1"):
        raise SystemExit("BB_BBUF must be 0 or 1 (64 KiB SRAM back-buffer window)")
    # v60: pinned SRAM data pages, e.g. BB_PIN_PAGES="16,1C" (4 KiB guest
    # pages as hex linear>>12). Up to 8. Costs 4160 B each; beyond 8 KiB of
    # them the default code cache shrinks to make room.
    pin_raw=os.environ.get("BB_PIN_PAGES","").replace(" ","")
    pins=[]
    if pin_raw:
        for tok in pin_raw.split(","):
            try: v=int(tok,16)
            except ValueError: raise SystemExit("BB_PIN_PAGES: hex page numbers, e.g. 16,1C")
            if not 0x10<=v<=0x9F: raise SystemExit("BB_PIN_PAGES: pages must be 10..9F (64 KiB..640 KiB)")
            if v in pins: raise SystemExit("BB_PIN_PAGES: duplicate page %X"%v)
            pins.append(v)
        if len(pins)>8: raise SystemExit("BB_PIN_PAGES: at most 8 pages")
    pin_bytes=len(pins)*4160
    pin_defs=(" BB_PIN_N=%d BB_PIN_LIST=%s"%(len(pins),",".join("0x%X"%p for p in pins))) if pins else ""
    default_kb=(232 if bbuf=="1" else 240) if paged=="1" else 192
    if pin_bytes>8192: default_kb-=(pin_bytes-8192+1023)//1024
    code_kb=os.environ.get("BB_CODE_KB",str(default_kb))
    # BB_GUEST_RAM_V1: total guest RAM (KiB). 1088 = legacy (1 MiB + HMA, no
    # extended memory). Above that, the rest is XMS/extended memory reported
    # by INT 15h 88h/E801h and reachable by protected-mode code only.
    guest_kb=os.environ.get("BB_GUEST_KB","4096")
    if not guest_kb.isdigit() or not 1088<=int(guest_kb)<=4608:
        raise SystemExit("BB_GUEST_KB must be 1088..4608 (total guest RAM, KiB)")
    guest_bytes=max(int(guest_kb)*1024,0x110020)
    if not code_kb.isdigit() or not 64<=int(code_kb)<=304:
        raise SystemExit("BB_CODE_KB must be 64..288 (SRAM code buffer, KiB)")
    if lcd_peri not in ("48000000","150000000"):
        raise SystemExit("BB_LCD_PERI_HZ must be 48000000 or 150000000")
    if lcd_hz not in ("24000000","40000000","75000000"):
        raise SystemExit("BB_LCD_SPI_HZ must be 24000000, 40000000 or 75000000")
    root=Path(__file__).resolve().parents[1]
    md=Path(a.microdos); b=Path(a.blitz86)
    sys_src=md/'src/system/md_dos2_system.c'
    pico_src=md/'pico/microdos_pico.c'
    cmake=md/'pico/CMakeLists.txt'
    if not all(f.is_file() for f in [sys_src,pico_src,cmake,b/'src/jit.c',b/'src/be_t2.c']):
        raise SystemExit('Missing expected microDOS/blitz86 files; no changes')
    sys_text=sys_src.read_text(encoding='utf8')
    pico_text=pico_src.read_text(encoding='utf8')
    sys_anchor='        left = budget - used;'
    pico_anchor='#define MD_GUEST_BYTES MD_X86_ADDRESS_SPACE'
    loop_anchor='        if(g_con.stats_requested){g_con.stats_requested=false;md_stats(start_us);}'
    if any([sys_text.count(sys_anchor)!=1,pico_text.count(pico_anchor)!=1,pico_text.count(loop_anchor)!=1]):
        raise SystemExit('Source anchors changed; originals untouched')
    # The stock no-AOT/no-cache fast path bypasses the main dispatcher entirely.
    # Exclude only the generated opt-in firmware from that fast path.
    fastpath = '#if !MICRODOS_SYSTEM_ENABLE_AOT && !MICRODOS_SYSTEM_ENABLE_CACHE && !defined(MICRODOS_ENABLE_JIT) && !defined(MICRODOS_ENABLE_NATIVE_V2) && !defined(MICRODOS_ENABLE_NATIVE3)'
    if sys_text.count(fastpath) != 1:
        raise SystemExit('Expected fast interpreter path not found exactly once; originals untouched')
    sys_text = sys_text.replace(fastpath, fastpath + ' && !defined(BLITZBUS_LIVE_BACKEND)', 1)
    sys_text='#include "bb_live.h"\n'+sys_text
    sys_text=sys_text.replace(sys_anchor,sys_anchor+'\n        if (bb_live_try(rt, left)) continue;',1)
    # V6 trace around interpreter fallback, including unexpected far returns.
    interp='            (void)md_interp_run_until_cs_change(rt, left);'
    if sys_text.count(interp)!=2:
        raise SystemExit('v6 interpreter call anchor mismatch; no files installed')
    # v21: step continuously after video mode begins. Check the guest PC
    # immediately after each instruction; no untraced run-until-CS-change gap.
    traced_interp=('            if (bb_live_v21_enabled(rt)) {\n'
        '                while (rt->stop_reason == MD_STOP_NONE &&\n'
        '                       rt->instructions - before < left) {\n'
        '                    bb_live_v21_before_step(rt);\n'
        '                    (void)md_interp_step(rt);\n'
        '                    if (bb_live_v21_after_step(rt)) break;\n'
        '                    if (rt->cpu.cs != trace_cs) break;\n'
        '                }\n'
        '            } else {\n'
        +interp+'\n'
        '            }')
    # Capture the original CS just before the continuous stepping loop.
    traced_interp=traced_interp.replace('                while (rt->stop_reason',
        '                const uint16_t trace_cs=rt->cpu.cs;\n                while (rt->stop_reason')
    sys_text=sys_text.replace(interp,
        '            bb_live_v17_interp_begin(rt);\n            bb_live_trace_interpreter(rt, "interp-before", before);\n'
        +traced_interp
        +'            bb_live_trace_interpreter(rt, "interp-after", before);')
    sys_text=sys_text.replace('#include "bb_live.h"\n', '#include "bb_live.h"\nextern void bb_live_trace_interpreter(MdRuntime *, const char *, uint64_t);\n', 1)
    # V7: guard BOTH interpreter fallback calls after they return.
    interp_after='            bb_live_trace_interpreter(rt, "interp-after", before);'
    if sys_text.count(interp_after)!=2:
        raise SystemExit('v7 interpreter guard anchor mismatch; no files installed')
    sys_text=sys_text.replace(interp_after,interp_after+'\n            bb_live_v7_after_interpreter(rt, "interp-exit", before);')
    sys_text=sys_text.replace('extern void bb_live_trace_interpreter(MdRuntime *, const char *, uint64_t);\n',
        'extern void bb_live_trace_interpreter(MdRuntime *, const char *, uint64_t);\nextern void bb_live_v7_after_interpreter(MdRuntime *, const char *, uint64_t);\nextern void bb_live_v17_interp_begin(MdRuntime *);\nextern int bb_live_v21_enabled(const MdRuntime *);\nextern void bb_live_v21_before_step(const MdRuntime *);\nextern int bb_live_v21_after_step(MdRuntime *);\n',1)


    pico_text='#include "bb_live.h"\n'+pico_text
    # BB_PSRAM_LAYOUT_DISK_AFTER_GUEST_V1: preserve all allocations; sort disk subsection after aligned guest.
    # The normal loader still creates a 360 KiB g_disk and guest is unchanged.
    _disk_decl = '__uninitialized_psram("md_disk")'
    if pico_text.count(_disk_decl) != 1:
        raise SystemExit("BB_PSRAM_LAYOUT_DISK_AFTER_GUEST_V1: expected one disk PSRAM declaration")
    pico_text = pico_text.replace(_disk_decl, '__uninitialized_psram("zz_md_disk")', 1)
    pico_text=pico_text.replace(pico_anchor,'#define MD_GUEST_BYTES (MD_X86_ADDRESS_SPACE + 0x10020u)',1)
    # BB_GUEST_RAM_V1: the boot memset (moved before the LCD by the SD
    # overlay, which anchors on it) stays at the 1 MiB + HMA window; extended
    # memory starts as uninitialised PSRAM, like real DRAM.
    # blitz86's SMC line map is indexed by host address >> 6: the guest buffer
    # must be 64-byte aligned (blitz86 refuses otherwise).
    guest_decl='__uninitialized_psram("md_guest") __attribute__((aligned(16)))'
    if pico_text.count(guest_decl)!=1:
        raise SystemExit('Guest buffer declaration changed; originals untouched')
    if paged=="1":
        # v40 (B86_PAGED): 4 KiB-aligned guest buffer at 640 KiB into a 2 MiB
        # window, so blitz86's 32 Ki-entry SMC line map indexes guest lines
        # without colliding with SRAM addresses (stores to SRAM-mapped pages
        # must find zero there). Costs up to ~2.6 MiB of otherwise unused PSRAM.
        if pico_text.count(guest_decl+'\n    g_guest[MD_GUEST_BYTES];')!=1:
            raise SystemExit('Guest buffer declaration changed; originals untouched')
        pico_text=pico_text.replace(guest_decl+'\n    g_guest[MD_GUEST_BYTES];',
            '__uninitialized_psram("md_guest") __attribute__((aligned(0x200000)))\n'
            '    g_guest_raw[0xA0000u + B86_RAM_BYTES];\n'
            '#define g_guest (g_guest_raw + 0xA0000u)',1)
    else:
        pico_text=pico_text.replace(guest_decl+'\n    g_guest[MD_GUEST_BYTES];',
            '__uninitialized_psram("md_guest") __attribute__((aligned(64)))\n    g_guest[B86_RAM_BYTES];',1)
    # Send the live counters on every Ctrl+] stats request, not only milestones.
    # Generate *actual C lines*.  The C format strings use escaped newline bytes.
    stats_block = r'''g_con.stats_requested=false;md_stats(start_us);
            md_say("[bb-live] backend=blitz86-thumb2 retired=%llu blocks=%llu ready=%d\n",
                (unsigned long long)bb_live_retired(),
                (unsigned long long)bb_live_blocks(),bb_live_ready());
            { BbLiveStats bs; bb_live_get_stats(&bs);
              md_say("[bb-live-owner] slices=%llu traps=%llu hooks=%llu page-syncs=%llu code-lines-changed=%llu tr-pages=%llu halts=%llu fail=%s\n",
                (unsigned long long)bs.slices,(unsigned long long)bs.traps,(unsigned long long)bs.hook_calls,
                (unsigned long long)bs.page_syncs,(unsigned long long)bs.page_invalidations,
                (unsigned long long)bs.tr_pages,(unsigned long long)bs.halts,bb_live_fail_reason());
              bb_live_print_extra(md_say); }
            { int rc; uint64_t delta,v,fb,d,b,e,h,o; uint16_t ei,ai;
              bb_live_status(&rc,&delta,&ei,&ai,&v,&fb,&d,&b,&e,&h,&o);
              md_say("[bb-jit] last-rc=%d chains=%llu smc-inval=%llu helpers=%llu\n",
                rc,(unsigned long long)b,(unsigned long long)e,(unsigned long long)o); }'''
    pico_text = pico_text.replace('g_con.stats_requested=false;md_stats(start_us);', stats_block, 1)
    if pico_text.count('[bb-live-owner]') != 1 or pico_text.count('[bb-jit]') != 1 or pico_text.count('bb_live_print_extra(md_say)') != 1:
        raise SystemExit('Live stats insertion failed')
    # Guard against the escaped-newline regression before emitting generated C.
    if r';\n            md_say' in pico_text:
        raise SystemExit('Literal escaped newlines found in generated C')
    # v53: raise the core voltage before the 300 MHz clock change. At the
    # default 1.10 V the RP2350 faulted deterministically (LDR right after
    # UBFX used the UBFX *input* as its index, always at a 16-byte aligned PC).
    clk_anchor='''static bool md_pico_set_clock(void)
{
#if MICRODOS_PICO_SYS_KHZ > 0
    if (!set_sys_clock_khz(MICRODOS_PICO_SYS_KHZ, false)) return false;'''
    if pico_text.count(clk_anchor)!=1:
        raise SystemExit('v53 clock anchor changed; originals untouched')
    vreg_mv=os.environ.get("BB_VREG_MV","1300")
    pico_text=pico_text.replace('#include "hardware/clocks.h"\n','#include "hardware/clocks.h"\n#include "hardware/vreg.h"\n',1)
    pico_text=pico_text.replace(clk_anchor,'''#ifndef BB_VREG_MV
#define BB_VREG_MV '''+vreg_mv+'''
#endif
static unsigned bb_vreg_mv_set;
static void bb_set_vreg_for_clock(uint32_t khz)
{
    if (khz <= 200000u || BB_VREG_MV == 0) return;
    enum vreg_voltage v; unsigned mv;
    if (BB_VREG_MV <= 1150) { v = VREG_VOLTAGE_1_15; mv = 1150; }
    else if (BB_VREG_MV <= 1200) { v = VREG_VOLTAGE_1_20; mv = 1200; }
    else if (BB_VREG_MV <= 1250) { v = VREG_VOLTAGE_1_25; mv = 1250; }
    else { v = VREG_VOLTAGE_1_30; mv = 1300; }
    vreg_set_voltage(v);
    sleep_ms(10);
    bb_vreg_mv_set = mv;
}

static bool md_pico_set_clock(void)
{
#if MICRODOS_PICO_SYS_KHZ > 0
    bb_set_vreg_for_clock(MICRODOS_PICO_SYS_KHZ);
    if (!set_sys_clock_khz(MICRODOS_PICO_SYS_KHZ, false)) return false;''',1)
    psram_say='''    md_say("  psram:   %lu KiB'''
    if pico_text.count(psram_say)!=1:
        raise SystemExit('v53 psram line changed; originals untouched')
    pico_text=pico_text.replace(psram_say,'''    md_say("  vcore:   %u mV%s\\n", bb_vreg_mv_set ? bb_vreg_mv_set : 1100u, bb_vreg_mv_set ? " (v53 raised)" : " (default)");
'''+psram_say,1)
    gen=root/'generated'; gen.mkdir(exist_ok=True)
    (gen/'bb_md_dos2_system.c').write_text(sys_text,encoding='utf8')
    (gen/'bb_microdos_pico.c').write_text(pico_text,encoding='utf8')
    overlay=md/'blitzbus-overlay'
    required=[overlay/n for n in ('bb_lcd_console.c','bb_lcd_console.h','mr_pico_ili9341.c','gfx_font5x7.c')]
    if not all(x.is_file() for x in required):
        raise SystemExit('Working v0.4 LCD overlay missing; run bb.bat upgrade first; no CMake changes')
    if 'BLITZBUS_LCD_CONSOLE' not in pico_text:
        raise SystemExit('Expected guarded v0.4 LCD calls not found; no changes')
    cm=cmake.read_text(encoding='utf8')
    block=f'''{BEGIN}
# The original microdos_pico target and original source files remain untouched.
md_pico_dos(blitzbus_pico_b86_dos 0 0 300000 0 0 0 0 0 0)
get_target_property(_bb_src blitzbus_pico_b86_dos SOURCES)
list(REMOVE_ITEM _bb_src "${{CMAKE_CURRENT_LIST_DIR}}/microdos_pico.c")
list(REMOVE_ITEM _bb_src "${{MD_ROOT}}/src/system/md_dos2_system.c")
list(APPEND _bb_src "{(gen/'bb_microdos_pico.c').as_posix()}"
    "{(gen/'bb_md_dos2_system.c').as_posix()}"
    "{(root/'src/bb_live.c').as_posix()}"
    "{(b/'src/interp.c').as_posix()}"
    "{(b/'src/jit.c').as_posix()}"
    "{(b/'src/be_t2.c').as_posix()}")
set_property(TARGET blitzbus_pico_b86_dos PROPERTY SOURCES "${{_bb_src}}")
target_include_directories(blitzbus_pico_b86_dos PRIVATE
    "{(root/'src').as_posix()}"
    "{(b/'include').as_posix()}"
    "${{MD_ROOT}}/src/system"
    "${{MD_ROOT}}/pico")
target_compile_definitions(blitzbus_pico_b86_dos PRIVATE
    B86_386_NATIVE_T1={native386} B86_MAXB=2048 B86_MAP_BITS=12 B86_FAST_BITS=10 B86_EVICT_CHUNK={eviction_chunk}u B86_EVICT_ROOM={eviction_room}u
    BB_CODE_BYTES={int(code_kb)*1024}u BB_HOT_BYTES={40960 if paged=="1" else 32768}u BB_HOT_THRESHOLD={hot}u BB_CPU_MODEL={cpu_model}u BB_NO_CHAIN={no_chain} BB_CHAIN_PROFILE=1
    {"B86_PAGED=1" if paged=="1" else ""} BB_BBUF_SRAM={bbuf}
    B86_CALLOC=bb_meta_calloc B86_FREE=bb_meta_free B86_NOW=bb_now_us B86_MISSES=bb_xip_misses
    BB386_PM_IRQ0={os.environ.get("BB_PM_IRQ0","1")} BB386_PM_KBD={os.environ.get("BB_PM_KBD","1")} B86_RAM_FUNCS=1 B86_PJ={os.environ.get("BB_PJ","1")} B86_PJ_HASH=512u B86_PJ_CPS=256u{(" B86_PJ_MAXI="+os.environ["BB_PJ_MAXI"]) if os.environ.get("BB_PJ_MAXI") else ""}{(" B86_PJ_CHAIN="+os.environ["BB_PJ_CHAIN"]) if os.environ.get("BB_PJ_CHAIN") else ""} BB_PJ_PSRAM={os.environ.get("BB_PJ_PSRAM","1")}{(" BB_PJ_CODE_KB="+os.environ["BB_PJ_CODE_KB"]) if os.environ.get("BB_PJ_CODE_KB") else ""}{(" BB_PJ_HOT_KB="+os.environ["BB_PJ_HOT_KB"]) if os.environ.get("BB_PJ_HOT_KB") else ""}{(" BB_META_BYTES="+str(int(os.environ["BB_META_KB"])*1024)+"u") if os.environ.get("BB_META_KB") else ""} B86_PM_RAM={os.environ.get("BB_PM_RAM","1")} B86_TV_SRAM={tv_sram} BB_PC_PROFILE={pc_prof}{mprof_defs}{pin_defs}
    PICO_STACK_SIZE=0x1000 PICO_CORE1_STACK_SIZE=0x1000
    MICRODOS_SYSTEM_ENABLE_AOT=0 MICRODOS_SYSTEM_ENABLE_CACHE=0
    BLITZBUS_LIVE_BACKEND=1
    B86_RAM_BYTES={guest_bytes}u
    BLITZBUS_LCD_CONSOLE=1
    MR_LCD_PANEL_ST7796S=1 MR_ILI9341_MADCTL=0xE8 MR_LCD_SPI_BAUD={lcd_hz}u BB_LCD_PERI_HZ={lcd_peri}u BB_LCD_LACE={lcd_lace})
target_sources(blitzbus_pico_b86_dos PRIVATE
    "{(root/'src/bb_lcd_console.c').as_posix()}"
    "${{MD_ROOT}}/blitzbus-overlay/mr_pico_ili9341.c"
    "${{MD_ROOT}}/blitzbus-overlay/gfx_font5x7.c")
target_include_directories(blitzbus_pico_b86_dos PRIVATE "${{MD_ROOT}}/blitzbus-overlay")
target_link_libraries(blitzbus_pico_b86_dos PRIVATE hardware_spi hardware_dma hardware_clocks pico_multicore)
# v51: quiesce before the USB reset interface's BOOTSEL reboot (picotool reboot -f)
target_link_options(blitzbus_pico_b86_dos PRIVATE "-Wl,--wrap=reset_usb_boot")
pico_set_program_name(blitzbus_pico_b86_dos "blitzBUS DOS + blitz86 gated")
{END}'''
    if BEGIN in cm or END in cm:
        if cm.count(BEGIN)!=1 or cm.count(END)!=1 or cm.index(END)<cm.index(BEGIN):
            raise SystemExit('Damaged CMake markers; existing file untouched')
        cm=cm[:cm.index(BEGIN)]+block+cm[cm.index(END)+len(END):]
    else:
        cm+='\n'+block+'\n'
    cmake.write_text(cm,encoding='utf8')
    import sys
    sys.path.insert(0, str(root/'sd_boot'))
    from bb_sd_overlay import apply as bb_sd_apply, disable as bb_sd_disable
    if os.environ.get('BB_SD_BOOT', '0') == '1':
        bb_sd_apply(md,root)
    else:
        bb_sd_disable(md)
    print('[blitzBUS] Installed opt-in live DOS/JIT target blitzbus_pico_b86_dos')
    print('[blitzBUS] Original DOS firmware source and target remain unchanged')
if __name__=='__main__':main()
