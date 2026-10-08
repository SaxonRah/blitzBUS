"""Install isolated live DOS/JIT proof target. Does not edit original C source."""
import argparse
from pathlib import Path

BEGIN = '# === blitzBUS v0.7 LIVE DOS BEGIN ==='
END = '# === blitzBUS v0.7 LIVE DOS END ==='

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--microdos',default=r'C:\microDOS')
    p.add_argument('--blitz86',default=r'C:\blitz86_v2')
    a=p.parse_args()
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
    sys_text=sys_text.replace(sys_anchor,sys_anchor+'\n        if (bb_live_try(rt)) continue;',1)
    pico_text='#include "bb_live.h"\n'+pico_text
    pico_text=pico_text.replace(pico_anchor,'#define MD_GUEST_BYTES (MD_X86_ADDRESS_SPACE + 0x10020u)',1)
    # Send the live counters on every Ctrl+] stats request, not only milestones.
    # Generate *actual C lines*.  The C format strings use escaped newline bytes.
    stats_block = r'''g_con.stats_requested=false;md_stats(start_us);
            md_say("[bb-live] backend=blitz86-thumb2 retired=%llu blocks=%llu ready=%d\n",
                (unsigned long long)bb_live_retired(),
                (unsigned long long)bb_live_blocks(),bb_live_ready());
            { uint64_t a,c,i,f,r; uint16_t cs,ip; uint8_t op;
              bb_live_diag(&a,&c,&i,&f,&r,&cs,&ip,&op);
              md_say("[bb-live-diag] attempts=%llu candidates=%llu init=%llu init_fail=%llu run_fail=%llu last=%04X:%04X op=%02X\n",
                (unsigned long long)a,(unsigned long long)c,(unsigned long long)i,
                (unsigned long long)f,(unsigned long long)r,cs,ip,op);
              md_say("[bb-live-diff] field=%s expected=%04X actual=%04X disabled=%d\n",
                bb_live_diff_field(),bb_live_diff_expected(),bb_live_diff_actual(),
                bb_live_ready()?0:1);
              { int rc; uint64_t delta,v,fb,d,b,e,h,o; uint16_t ei,ai;
                bb_live_status(&rc,&delta,&ei,&ai,&v,&fb,&d,&b,&e,&h,&o);
                md_say("[bb-live-rc] code=%d delta=%llu expected_ip=%04X actual_ip=%04X budget=%llu exit=%llu halt=%llu other=%llu\n",
                   rc,(unsigned long long)delta,ei,ai,(unsigned long long)b,
                   (unsigned long long)e,(unsigned long long)h,(unsigned long long)o);
                md_say("[bb-live-guard] verified=%llu fallback=%llu disabled=%llu\n",
                   (unsigned long long)v,(unsigned long long)fb,(unsigned long long)d); }
            }'''
    pico_text = pico_text.replace('g_con.stats_requested=false;md_stats(start_us);', stats_block, 1)
    if pico_text.count('[bb-live-rc]') != 1 or pico_text.count('[bb-live-guard]') != 1:
        raise SystemExit('Live stats insertion failed')
    # Guard against the escaped-newline regression before emitting generated C.
    if r';\n            md_say' in pico_text:
        raise SystemExit('Literal escaped newlines found in generated C')
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
    B86_MAXB=256 B86_MAP_BITS=10
    BLITZBUS_LIVE_BACKEND=1
    BLITZBUS_LCD_CONSOLE=1
    MR_LCD_PANEL_ST7796S=1 MR_ILI9341_MADCTL=0xE8 MR_LCD_SPI_BAUD=40000000u)
target_sources(blitzbus_pico_b86_dos PRIVATE
    "${{MD_ROOT}}/blitzbus-overlay/bb_lcd_console.c"
    "${{MD_ROOT}}/blitzbus-overlay/mr_pico_ili9341.c"
    "${{MD_ROOT}}/blitzbus-overlay/gfx_font5x7.c")
target_include_directories(blitzbus_pico_b86_dos PRIVATE "${{MD_ROOT}}/blitzbus-overlay")
target_link_libraries(blitzbus_pico_b86_dos PRIVATE hardware_spi hardware_dma)
pico_set_program_name(blitzbus_pico_b86_dos "blitzBUS DOS + blitz86 gated")
{END}'''
    if BEGIN in cm or END in cm:
        if cm.count(BEGIN)!=1 or cm.count(END)!=1 or cm.index(END)<cm.index(BEGIN):
            raise SystemExit('Damaged CMake markers; existing file untouched')
        cm=cm[:cm.index(BEGIN)]+block+cm[cm.index(END)+len(END):]
    else:
        cm+='\n'+block+'\n'
    cmake.write_text(cm,encoding='utf8')
    print('[blitzBUS] Installed opt-in live DOS/JIT target blitzbus_pico_b86_dos')
    print('[blitzBUS] Original DOS firmware source and target remain unchanged')
if __name__=='__main__':main()
