#!/usr/bin/env python3
"""DOS622 media hot-swap, VGA-color LCD, unlimited color console runner.

V2.1 fixes the historically valid SD clock-fix `sd_after`/`manifest_after`
SHA fields. It preserves V2 installation state/tag for future compatibility.

No Git patches. Commands: selftest, probe, apply, verify, restore.
Do not change SD contents or DOS2 paths. Refuses unexpected source layouts.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,subprocess,tempfile,sys
from pathlib import Path
import bb_dos622_atbios_v1 as chain

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_SWAP_LCD_V2'
STATE='.bb_dos622_swap_lcd_v2_state'
SRC_SD='sd_boot/bb_dos622_sd.inc'
SRC_SDBOOT='sd_boot/bb_sd_boot.c'
SRC_BIOS='src/bb_dos622_bios.inc'
SRC_LIVE='src/bb_live.c'
SRC_LCD='src/bb_lcd_console.c'
SRC_COLOR_RUN='scripts/bb_live_run_dos622_color.ps1'
SRC_BASE_RUN='scripts/bb_live_run.ps1'
NEW_RUN='scripts/bb_live_run_dos622_swap.ps1'
OLD_HOST='scripts/bb_dos622_color_host.ps1'
NEW_HOST='scripts/bb_dos622_swap_color_host.ps1'
SH=lambda b:hashlib.sha256(b).hexdigest()

def as_text(data):
    bom=data.startswith(b'\xef\xbb\xbf')
    s=data.decode('utf-8-sig')
    if '\r\n' in s and '\n' in s.replace('\r\n',''):
        raise ValueError('mixed line endings')
    return s.replace('\r\n','\n'), ('\r\n' if '\r\n' in s else '\n'),bom

def pack(s,e,bom):return (b'\xef\xbb\xbf' if bom else b'')+s.replace('\n',e).encode('utf8')

def exact(s,a,b,label):
    n=s.count(a)
    if n!=1:raise ValueError(f'{label}: expected one source anchor, found {n}')
    return s.replace(a,b,1)

SD_A_FUNC=r'''/* BB_DOS622_SWAP_LCD_V2: floppy A media exchange, DOS622 only.
 * Open new FAT12 image BEFORE closing old; invalid/missing leaves old intact.
 * NOSYS on second disk is intentional: SETUP floppy 2+ has no IO.SYS.
 */
static bool bb622_swap_fat12_valid(const uint8_t *b)
{
    return b[510]==0x55u && b[511]==0xAAu &&
        (b[0]==0xEBu || b[0]==0xE9u) &&
        b[11]==0u && b[12]==2u && b[13]==1u &&
        b[14]==1u && b[15]==0u && b[16]==2u &&
        b[17]==224u && b[18]==0u &&
        b[19]==0x40u && b[20]==0x0Bu &&
        b[22]==9u && b[23]==0u &&
        b[24]==18u && b[25]==0u && b[26]==2u && b[27]==0u;
}
bool bb_sd_dos622_take_a_change(void)
{
    const bool result=bb622_swap_a_changed;
    bb622_swap_a_changed=false;
    return result;
}
bool bb_sd_dos622_select_a(unsigned n)
{
    FIL *candidate;
    FRESULT fr;
    UINT got=0;
    uint8_t bs[512];
    char path[96];
    if(!bb622_disk_open || n<1u || n>9u)return false;
    if(n==bb622_swap_a_number)return true;
    if(n==1u) {
        if(snprintf(path,sizeof path,"0:/BLITZBUS/DOS622.IMG") >= (int)sizeof path)return false;
    } else if(snprintf(path,sizeof path,"0:/BLITZBUS/DOS622%u.IMG",n) >= (int)sizeof path)return false;
    bb622_retime_spi1();
    candidate = (bb622_swap_active==&bb622_disk) ? &bb622_swap_alt : &bb622_disk;
    fr=f_open(candidate,path,FA_READ);
    if(fr!=FR_OK) {
        printf("[bb622-swap] A:%u FAIL open fr=%d (previous disk retained)\n",n,(int)fr);
        return false;
    }
    if(f_size(candidate)!=1474560u ||
       f_read(candidate,bs,512u,&got)!=FR_OK || got!=512u ||
       !bb622_swap_fat12_valid(bs)) {
        printf("[bb622-swap] A:%u FAIL image must be 1440 KiB FAT12 (previous disk retained)\n",n);
        (void)f_close(candidate);
        return false;
    }
    (void)f_close(bb622_swap_active);
    bb622_swap_active=candidate;
    bb622_swap_a_number=n;
    bb622_swap_a_changed=true;
    printf("[bb622-swap] A:%u OK read-only; BIOS media changed\n",n);
    fflush(stdout);
    return true;
}
'''

B_MEDIA=r'''/* BB_DOS622_SWAP_LCD_V2: track successful B media replacements for BIOS AH=16h. */
bool bb_sd_dos622_take_b_change(void)
{
    bool changed=bb622_swap_b_changed;
    bb622_swap_b_changed=false;
    return changed;
}
'''

LIVE_HELPER=r'''/* BB_DOS622_SWAP_LCD_V2: private CDC command prefix FS(1Ch), drive, digit.
 * Normal BIOS keyboard bytes remain unchanged; no UART/SD concurrency.
 * Host sends the whole command while DOS is paused at the floppy prompt.
 */
static uint8_t bb622_swap_step;
static uint8_t bb622_swap_drive;
static uint64_t bb622_swap_started_us;
static void bb622_swap_receive(unsigned ch)
{
    const uint64_t now=bb_now_us();
    if(bb622_swap_step && now-bb622_swap_started_us>2000000ull)bb622_swap_step=0u;
    if(bb622_swap_step==0u) {
        if(ch==0x1Cu){bb622_swap_step=1u;bb622_swap_started_us=now;}
        return;
    }
    bb622_swap_started_us=now;
    if(bb622_swap_step==1u) {
        if(ch=='A'||ch=='B') {bb622_swap_drive=(uint8_t)ch;bb622_swap_step=2u;}
        else bb622_swap_step=0u;
        return;
    }
    bb622_swap_step=0u;
    if(ch<'1'||ch>'9')return;
    {
        unsigned number=ch-'0';
        bool success=(bb622_swap_drive=='A') ? bb_sd_dos622_select_a(number) :
                                              bb_sd_b_select(number);
        if(bb622_swap_drive=='B') {
            printf("[bb622-swap] B:%u %s; BIOS media %s\n",number,
                   success?"OK":"FAIL (previous disk retained)",success?"changed":"unchanged");
            fflush(stdout);
        }
    }
}
'''

LCD_HELPER=r'''/* BB_DOS622_SWAP_LCD_V2: VGA text attributes in PSRAM, not RP2350 SRAM.
 * Preserve DOS2 monochrome diagnostic HUD and video mode-13h DMA path.
 */
static uint8_t __uninitialized_psram("bb622_lcd_attr") bb622_lcd_attr[ROWS][COLS];
static const uint16_t bb622_vga16[16]={
    0x0000u,0x0015u,0x0540u,0x0555u,
    0xA800u,0xA815u,0xAAA0u,0xAD55u,
    0x52AAu,0x52BFu,0x57EAu,0x57FFu,
    0xFAAAu,0xFABFu,0xFFE0u,0xFFFFu
};
/* Common IBM CP437 single/double box drawing, shaded and block cells.
 * Coordinates are inside the preexisting 6x8 monochrome font cell. */
static bool bb622_cp437_dot(unsigned c,unsigned x,unsigned y)
{
    const bool h=(y==3u),v=(x==2u),dh=(y==2u||y==5u),dv=(x==1u||x==4u);
    switch(c) {
    case 0xB0u:return ((x+y*3u)&3u)==0u;
    case 0xB1u:return ((x+y)&1u)==0u;
    case 0xB2u:return ((x+y*3u)&3u)!=0u;
    case 0xDBu:return true;
    case 0xDCu:return y>=4u;
    case 0xDFu:return y<4u;
    case 0xDDu:return x<3u;
    case 0xDEu:return x>=3u;
    case 0xB3u:return v;
    case 0xC4u:return h;
    case 0xDAu:return (h&&x>=2u)||(v&&y>=3u);
    case 0xBFu:return (h&&x<=2u)||(v&&y>=3u);
    case 0xC0u:return (h&&x>=2u)||(v&&y<=3u);
    case 0xD9u:return (h&&x<=2u)||(v&&y<=3u);
    case 0xC3u:return v||(h&&x>=2u);
    case 0xB4u:return v||(h&&x<=2u);
    case 0xC2u:return h||(v&&y>=3u);
    case 0xC1u:return h||(v&&y<=3u);
    case 0xC5u:return h||v;
    case 0xBAu:return dv;
    case 0xCDu:return dh;
    case 0xC9u:return (dh&&x>=1u)||(dv&&y>=2u);
    case 0xBBu:return (dh&&x<=4u)||(dv&&y>=2u);
    case 0xC8u:return (dh&&x>=1u)||(dv&&y<=5u);
    case 0xBCu:return (dh&&x<=4u)||(dv&&y<=5u);
    case 0xCCu:return dv||(dh&&x>=1u);
    case 0xB9u:return dv||(dh&&x<=4u);
    case 0xCBu:return dh||(dv&&y>=2u);
    case 0xCAu:return dh||(dv&&y<=5u);
    case 0xCEu:return dh||dv;
    default:return false;
    }
}
static bool bb622_cp437_shape(unsigned c)
{
    switch(c) {
    case 0xB0u:case 0xB1u:case 0xB2u:case 0xDBu:case 0xDCu:
    case 0xDFu:case 0xDDu:case 0xDEu:case 0xB3u:case 0xC4u:
    case 0xDAu:case 0xBFu:case 0xC0u:case 0xD9u:case 0xC3u:
    case 0xB4u:case 0xC2u:case 0xC1u:case 0xC5u:case 0xBAu:
    case 0xCDu:case 0xC9u:case 0xBBu:case 0xC8u:case 0xBCu:
    case 0xCCu:case 0xB9u:case 0xCBu:case 0xCAu:case 0xCEu:return true;
    default:return false;
    }
}
static void bb622_lcd_draw_cell(uint16_t *dst,unsigned pitch,unsigned xx,
                                 unsigned c,uint8_t attr)
{
    const uint16_t fg=bb622_vga16[attr&15u];
    const uint16_t bg=bb622_vga16[(attr>>4u)&7u];
    const bool special=bb622_cp437_shape(c);
    const uint8_t *g=gfx_font5x7[(c>=32u&&c<=127u?c:(unsigned)'?')-32u];
    for(unsigned y=0;y<8u;y++)for(unsigned x=0;x<6u;x++) {
        bool on=special?bb622_cp437_dot(c,x,y):
                     (y<7u&&x<5u&&(g[x]&(1u<<y))!=0u);
        dst[y*pitch+xx+x]=on?fg:bg;
    }
}
'''


def sd_change(raw):
    s,e,b=as_text(raw)
    if TAG in s:raise ValueError('already patched A:')
    s=exact(s,'static FIL bb622_disk;','''static FIL bb622_disk;
static FIL bb622_swap_alt;
static FIL *bb622_swap_active=&bb622_disk;
static unsigned bb622_swap_a_number=1u;
static bool bb622_swap_a_changed;''','SD A static')
    s=exact(s,'rc = f_read(&bb622_disk, dst, 512u, &got);', 'rc = f_read(bb622_swap_active, dst, 512u, &got);','SD A read')
    s=exact(s,'rc = f_lseek(&bb622_disk, (FSIZE_t)lba * 512u);','rc = f_lseek(bb622_swap_active, (FSIZE_t)lba * 512u);','SD A seek')
    s=exact(s,'    bb622_disk_open = false;\n    bb622_read_calls = bb622_read_errors = 0;',
            '    bb622_disk_open = false;\n    bb622_swap_active=&bb622_disk;bb622_swap_a_number=1u;bb622_swap_a_changed=false;\n    bb622_read_calls = bb622_read_errors = 0;', 'SD A init')
    s=exact(s,'/* DOS 6.x floppy boot candidates need the ordinary 1.44MB FAT12 layout.',SD_A_FUNC+'\n/* DOS 6.x floppy boot candidates need the ordinary 1.44MB FAT12 layout.','SD A funcs')
    return pack(s,e,b)

def sdboot_change(raw):
    s,e,b=as_text(raw)
    if TAG in s:raise ValueError('already patched B:')
    s=exact(s,'static bool bb_b_open;','static bool bb_b_open;\nstatic bool bb622_swap_b_changed;','SD B state')
    s=exact(s,'    bb_b_open = false;\n    bb_b_number = 0u;',
            '    bb_b_open = false;\n    bb622_swap_b_changed=false;\n    bb_b_number = 0u;','SD B init')
    a='''        bb_b_open=true;
        bb_b_number=selected;
        printf("[bb-sd-b] LIVE SWITCH B: disk=%u OK\\n",selected);'''
    b2='''        bb_b_open=true;
        bb_b_number=selected;
        if(bb_sd_dos622_active())bb622_swap_b_changed=true; /* BB_DOS622_SWAP_LCD_V2 */
        printf("[bb-sd-b] LIVE SWITCH B: disk=%u OK\\n",selected);'''
    s=exact(s,a,b2,'SD B successful swap')
    s=exact(s,'/* BB_DESCENT_LIVESWAP_V1. Called only by the emulator\'s INT F6 service. */',
            B_MEDIA+'\n/* BB_DESCENT_LIVESWAP_V1. Called only by the emulator\'s INT F6 service. */','SD B status')
    return pack(s,e,b)

def bios_change(raw):
    s,e,b=as_text(raw)
    if TAG in s:raise ValueError('already patched BIOS')
    anchor='extern bool bb_sd_b_read_sector(uint32_t lba,uint8_t *dst,size_t size);'
    s=exact(s,anchor,anchor+'''
/* BB_DOS622_SWAP_LCD_V2: BIOS floppy media-change notifications */
extern bool bb_sd_dos622_take_a_change(void);
extern bool bb_sd_dos622_take_b_change(void);''','BIOS extern')
    s=exact(s,'    if(fn==0x16u) {bb622_status(c,0u,0u);return true;}',
            '    if(fn==0x16u) {bb622_status(c,bb_sd_dos622_take_b_change()?0x06u:0u,0u);return true;}','BIOS B change')
    s=exact(s,'    if (fn == 0x16u) { bb622_status(c, drive == 0u ? 0u : 0x80u, 0u); return true; }',
            '    if (fn == 0x16u) { bb622_status(c, drive == 0u ? (bb_sd_dos622_take_a_change()?0x06u:0u) : 0x80u, 0u); return true; }','BIOS A change')
    return pack(s,e,b)

def live_change(raw):
    s,e,b=as_text(raw)
    if TAG in s:raise ValueError('already patched LIVE')
    a='static void bb_v23_poll_input(void) {'
    s=exact(s,a,'''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
extern bool bb_sd_dos622_select_a(unsigned n);
extern bool bb_sd_b_select(unsigned n);
'''+LIVE_HELPER+'''#endif
'''+a,'LIVE helper')
    a='''    /* v33: once video owns the console, this poll is the only reader of the
       serial port, so Ctrl+] (0x1D) is handled here instead of reaching the
       guest keyboard queue. */'''
    b2='''    /* BB_DOS622_SWAP_LCD_V2: protected out-of-band 3-byte disk command.
       1Ch A/B n; never forwards control bytes into DOS keyboard. */
    if(bb_sd_dos622_active()) {
        if(bb622_swap_step || c==0x1C) {
            if(c>=0)bb622_swap_receive((unsigned)c);
            else if(bb_now_us()-bb622_swap_started_us>2000000ull)bb622_swap_step=0u;
            return;
        }
    }
'''+a
    s=exact(s,a,b2,'LIVE serial interceptor')
    return pack(s,e,b)

def lcd_change(raw):
    s,e,b=as_text(raw)
    if TAG in s:raise ValueError('already patched LCD')
    s=exact(s,'static uint8_t bb622_text_owns_lcd;','static uint8_t bb622_text_owns_lcd;\n'+LCD_HELPER,'LCD helper')
    a='''    for(unsigned x=0;x<COLS;x++) draw_glyph(pixels,COLS*CW,x*CW,0,cells[r][x],0xFFFFu,0x0000u);'''
    b2='''    for(unsigned x=0;x<COLS;x++) {
        if(bb622_text_owns_lcd)bb622_lcd_draw_cell(pixels,COLS*CW,x*CW,
            cells[r][x],bb622_lcd_attr[r][x]);
        else draw_glyph(pixels,COLS*CW,x*CW,0,cells[r][x],0xFFFFu,0x0000u);
    }'''
    s=exact(s,a,b2,'LCD draw loop')
    s=exact(s,'        memset(cells,0,sizeof cells);\n        memset(dirty,1,sizeof dirty);',
            '        memset(cells,0,sizeof cells);\n        memset(bb622_lcd_attr,0x07,sizeof bb622_lcd_attr);\n        memset(dirty,1,sizeof dirty);','LCD takeover reset')
    a='''            const uint8_t ch=(raw>=32u && raw<=126u) ? raw : (uint8_t)' ';
            if (cells[y][x] != ch) { cells[y][x]=ch; dirty_row=1u; }'''
    b2='''            const uint8_t ch=(raw>=32u) ? raw : (uint8_t)' ';
            const uint8_t attr=text[(y*COLS+x)*2u+1u];
            if (cells[y][x]!=ch || bb622_lcd_attr[y][x]!=attr) {
                cells[y][x]=ch;bb622_lcd_attr[y][x]=attr;dirty_row=1u;
            }'''
    s=exact(s,a,b2,'LCD B800 char+attr mirror')
    s=exact(s,'            printf("[bb622-lcdtext] B800 text shown on LCD; updated-rows=%u\\n",changed_rows);',
            '            printf("[bb622-lcdcolor] 16-color VGA B800 text on LCD; updated-rows=%u\\n",changed_rows);','LCD log')
    return pack(s,e,b)

# V2: independently generate a functional color console from the original
# live runner if the previous optional color-runner artifact is absent.
# No previous runner or host file is overwritten, even with this fallback.
COLOR_HELPER_TEMPLATE=Path(__file__).with_name('bb_dos622_color_host.ps1')

def generate_color_runner_from_original(raw):
    s,e,b=as_text(raw)
    a='    [switch]$PhaseProfile'
    s=exact(s,a,"    [switch]$PhaseProfile,\n    [ValidateSet('Screen','Events','Raw')]\n    [string]$ConsoleView='Screen'", 'base runner parameter')
    a='$serial=$null'
    s=exact(s,a,"# BB_DOS622_COLOR_CELLS_V1: independent host display, raw log intact.\nif ($ConsoleView -ne 'Raw') { . (Join-Path $PSScriptRoot 'bb_dos622_color_host.ps1') }\n"+a,'base runner color helper')
    a='            Write-Host -NoNewline $chunk'
    s=exact(s,a,"            if ($ConsoleView -eq 'Raw') { Write-Host -NoNewline $chunk }\n            else { Write-BbDos622ColorConsoleChunk $chunk $ConsoleView }", 'base runner raw display')
    if s.count('[System.IO.File]::AppendAllText($log,$chunk)')!=1:
        raise ValueError('base runner raw logging anchor missing; will not generate')
    a='        Start-Sleep -Milliseconds 15'
    s=exact(s,a,"        if ($ConsoleView -eq 'Screen') { Show-BbDos622ColorFrame }\n"+a,'base runner redraw cadence')
    a='                    if($k.Key -eq [ConsoleKey]::Enter){'
    special=r'''                    $bb622SpecialKey = switch ([string]$k.Key) {
                        'F1' {'OP'} 'F2' {'OQ'} 'F3' {'OR'} 'F4' {'OS'}
                        'F5' {'[15~'} 'F6' {'[17~'} 'F7' {'[18~'} 'F8' {'[19~'}
                        'F9' {'[20~'} 'F10' {'[21~'} 'F11' {'[23~'} 'F12' {'[24~'}
                        'UpArrow' {'[A'} 'DownArrow' {'[B'}
                        'RightArrow' {'[C'} 'LeftArrow' {'[D'}
                        'Home' {'[H'} 'End' {'[F'}
                        'Insert' {'[2~'} 'Delete' {'[3~'}
                        'PageUp' {'[5~'} 'PageDown' {'[6~'}
                        default {''}
                    }
                    if ($bb622SpecialKey) {
                        $serial.Write(([string][char]27) + $bb622SpecialKey)
                    } elseif($k.Key -eq [ConsoleKey]::Enter){'''
    s=exact(s,a,special,'base runner extended keys')
    return pack(s,e,b)

def host_change(raw):
    s,e,b=as_text(raw)
    if TAG in s:raise ValueError('already patched host')
    s=exact(s,'[int]$Seconds=180,','[int]$Seconds=0,','host default timeout')
    s=exact(s,'while((Get-Date) -lt $deadline){',
            'while($Seconds -le 0 -or (Get-Date) -lt $deadline){','host unlimited run')
    # The old runner already handles Enter and F1-F12 via a VT mapping.
    a='                    $k=[Console]::ReadKey($true)'
    b2='''                    $k=[Console]::ReadKey($true)
                    # BB_DOS622_SWAP_LCD_V2: F9 -> drive A/B -> disk number.
                    # Never pass menu selection to the DOS keyboard.
                    if($k.Key -eq [ConsoleKey]::F9){
                        $bb622SwapStage=1
                        [Console]::Title='blitzBUS floppy swap | F9: choose A or B (Esc cancels)'
                        continue
                    }
                    if($bb622SwapStage -eq 1){
                        if($k.Key -eq [ConsoleKey]::Escape){
                            $bb622SwapStage=0;[Console]::Title='blitzBUS DOS 6.22 | floppy selection canceled'
                        } elseif($k.KeyChar -eq 'a' -or $k.KeyChar -eq 'A' -or
                                 $k.KeyChar -eq 'b' -or $k.KeyChar -eq 'B'){
                            $bb622SwapDrive=([string]$k.KeyChar).ToUpperInvariant()
                            $bb622SwapStage=2
                            [Console]::Title="blitzBUS floppy swap | $($bb622SwapDrive): press disk number 1..9 (Esc cancels)"
                        }
                        continue
                    }
                    if($bb622SwapStage -eq 2){
                        if($k.Key -eq [ConsoleKey]::Escape){
                            [Console]::Title='blitzBUS DOS 6.22 | floppy selection canceled'
                        } elseif($k.KeyChar -ge '1' -and $k.KeyChar -le '9'){
                            $number=[string]$k.KeyChar
                            if($bb622SwapDrive -eq 'B' -and [int]$number -gt 5){
                                [Console]::Title='blitzBUS B: supports DESCENT1..5.IMG only; press F9 to retry'
                            }else{
                                $serial.Write(([string][char]0x1C)+$bb622SwapDrive+$number)
                                [Console]::Title="blitzBUS | sent $($bb622SwapDrive):$number; check ACK then press Enter in DOS"
                            }
                        }
                        $bb622SwapStage=0
                        continue
                    }'''
    s=exact(s,a,b2,'host key input')
    a='$quit=$false'
    s=exact(s,a,a+'\n$bb622SwapStage=0\n$bb622SwapDrive=""','host swap init')
    if 'bb_dos622_color_host.ps1' not in s or '$ConsoleView' not in s:
        raise ValueError('expected DOS6 color runner missing')
    s=exact(s,'bb_dos622_color_host.ps1','bb_dos622_swap_color_host.ps1','host helper reference')
    return pack(s,e,b)

def screen_host_change(raw):
    s,e,b=as_text(raw)
    if TAG in s:raise ValueError('host helper already patched')
    a="    if ($Line -match '^\\[bb622-watch\\].*?insns=(\\d+)') {"
    # Exact line from installed bb_dos622_color_host.ps1 uses literal backslashes.
    a=r"    if ($Line -match '^\[bb622-watch\].*?insns=(\d+)') {"
    b2=r"""    # BB_DOS622_SWAP_LCD_V2: report disk swaps even in the static screen view.
    if ($Line -match '^\[bb622-swap\]') {
        $script:bbColorSwapAck=$Line
        try { [Console]::Title=($Line+' | Enter in DOS after OK') } catch {}
        $script:bbColorLastScreenChange=[datetime]::UtcNow
        if ($View -eq 'Events') { Write-Host $Line -ForegroundColor Cyan }
        return
    }
"""+a
    s=exact(s,a,b2,'host status parser')
    a="        if ($script:bbColorActive -and $screenAge -ge 5) {"
    b2="""        if ($script:bb622SwapStage -eq 1) {
            [Console]::Title='blitzBUS F9 floppy swap | choose A (DOS 6.22) or B (Descent); Esc cancels'
        } elseif ($script:bb622SwapStage -eq 2) {
            [Console]::Title="blitzBUS F9 floppy swap | drive $($script:bb622SwapDrive) disk 1..9; Esc cancels"
        } elseif ($script:bbColorActive -and $screenAge -ge 5) {"""
    s=exact(s,a,b2,'host swap menu title')
    return pack(s,e,b)

SOURCES={SRC_SD:sd_change,SRC_SDBOOT:sdboot_change,SRC_BIOS:bios_change,SRC_LIVE:live_change,SRC_LCD:lcd_change}

# V2.1: historical, REPOSITORY-VERIFIED schema. This is the repair record
# emitted by BB_DOS622_SD_CLOCKFIX_V1. Never alter its 'before' digests.
# Deliberately do not add broad suffix patterns to ATBIOS's global parser.
CLOCKFIX_REPAIR='.bb_dos622_sd_clockfix_v1_state/repair.json'
CLOCKFIX_FIELDS=frozenset({'version','sd_before','sd_after','manifest_before','manifest_after'})


def update_known_metadata(raw:bytes,changes:dict[str,str],rel:str):
    if rel!=CLOCKFIX_REPAIR:
        return chain._update_metadata(raw,changes,rel)
    try:
        doc=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ValueError(f'Invalid historic clockfix record {rel}: {exc}') from exc
    if (not isinstance(doc,dict) or doc.get('version')!=1
            or set(doc)!=CLOCKFIX_FIELDS):
        raise ValueError(f'Unexpected clockfix record schema {rel}; no changes made')
    for k in ('sd_before','sd_after','manifest_before','manifest_after'):
        v=doc[k]
        if not isinstance(v,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',v):
            raise ValueError(f'Invalid SHA {rel}:{k}')
    replacements=[]
    found={}
    for match in chain.KV_SHA.finditer(raw):
        key=match.group('key').decode('ascii','replace')
        if key in found:raise ValueError(f'Duplicate SHA field {rel}:{key}')
        found[key]=True
        if key not in ('sd_after','manifest_after'):continue
        digest=match.group('digest').decode('ascii')
        new=changes.get(digest.lower())
        if new is not None and new!=digest.lower():
            if not re.fullmatch(r'[0-9a-f]{64}',new):
                raise ValueError(f'Invalid mapped SHA {rel}:{key}')
            rep=(new.upper() if digest.isupper() else new).encode('ascii')
            replacements.append((match.start('digest'),match.end('digest'),rep))
    if set(found)!=CLOCKFIX_FIELDS-{'version'}:
        raise ValueError(f'Unexpected SHA field multiplicity in {rel}')
    if not replacements:return raw,0
    result=bytearray(raw)
    for start,end,value in replacements:
        if end-start!=64 or len(value)!=64:raise AssertionError('SHA length mismatch')
        result[start:end]=value
    updated=bytes(result)
    after=json.loads(updated)
    assert after['sd_before']==doc['sd_before']
    assert after['manifest_before']==doc['manifest_before']
    assert len(updated)==len(raw)
    return updated,len(replacements)


def cascade(root:Path,old_new):
    originals=chain.active_metadata(root)
    after=dict(originals)
    changes={SH(old):SH(new) for old,new in old_new.values() if old is not None}
    for _ in range(len(originals)*8+12):
        any_change=False
        for rel,raw in originals.items():
            transformed,_=update_known_metadata(raw,changes,rel)
            if transformed!=after[rel]:after[rel]=transformed;any_change=True
            if transformed!=raw and changes.get(SH(raw))!=SH(transformed):
                changes[SH(raw)]=SH(transformed);any_change=True
        if not any_change:break
    else:raise ValueError('SHA cascade failed convergence')
    return {rel:(orig,after[rel]) for rel,orig in originals.items() if orig!=after[rel]}

def prepare(root=ROOT,verbose=True):
    if (root/STATE).exists():raise ValueError('already installed; run verify or restore')
    if (root/'.bb_dos622_swap_lcd_v1_state').exists():
        raise ValueError('V1 appears installed; do not stack V2 over it')
    # Detect missing prior layers without rewriting their artifacts.
    for rel,m in [(SRC_LCD,b'BB_DOS622_LCD_TEXT_V2'),(SRC_BIOS,b'BB_DOS622_FLOPPY_B_V1'),
                  (SRC_LIVE,b'BB_DOS622_VGA0B_KEYS_V1'),(SRC_SD,b'BB_DOS622_IPL_V1')]:
        if not (root/rel).is_file() or m not in (root/rel).read_bytes():
            raise ValueError('expected predecessor missing '+rel)
    for rel in (NEW_RUN,NEW_HOST):
        if (root/rel).exists():raise ValueError('refusing to overwrite '+rel)
    updates={}
    for rel,fn in SOURCES.items():
        old=(root/rel).read_bytes();new=fn(old)
        updates[rel]=(old,new)
    if (root/SRC_COLOR_RUN).is_file():
        runner=(root/SRC_COLOR_RUN).read_bytes()
        runner_origin='existing color runner'
    else:
        if not (root/SRC_BASE_RUN).is_file():
            raise ValueError('missing original live runner '+SRC_BASE_RUN)
        runner=generate_color_runner_from_original((root/SRC_BASE_RUN).read_bytes())
        runner_origin='generated from original runner'
    if (root/OLD_HOST).is_file():
        helper=(root/OLD_HOST).read_bytes()
    else:
        if not COLOR_HELPER_TEMPLATE.is_file():
            raise ValueError('bundled host helper missing: '+str(COLOR_HELPER_TEMPLATE))
        helper=COLOR_HELPER_TEMPLATE.read_bytes()
    updates[NEW_RUN]=(None,host_change(runner))
    updates[NEW_HOST]=(None,screen_host_change(helper))
    updates.update(cascade(root,{k:v for k,v in updates.items() if v[0] is not None}))
    if verbose:
        for rel,(old,new) in updates.items():
            if rel in SOURCES or rel in (NEW_RUN,NEW_HOST):print(f'{rel}: {len(old) if old is not None else "NEW"}->{len(new)} SHA {SH(new)[:12]}')
        print('Runner source:',runner_origin,'; host helper:', 'existing' if (root/OLD_HOST).is_file() else 'bundled')
        print('Metadata cascade:',len(updates)-7,'files; PROBE PASS; no edits')
    return updates

def atomic(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.bb622-tmp')
    try:
        tmp.write_bytes(data);os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def verify(root=ROOT):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError('missing install state')
    m=json.loads(p.read_bytes())
    if m.get('tag')!=TAG:raise ValueError('wrong manifest tag')
    for row in m['files']:
        rel=row['path']
        if Path(rel).is_absolute() or '..' in Path(rel).parts:raise ValueError('unsafe path '+rel)
        if not (root/rel).is_file() or SH((root/rel).read_bytes())!=row['installed']:
            raise ValueError('installed SHA mismatch '+rel)
        if row['original'] is not None:
            bp=root/STATE/row['backup']
            if not bp.is_file() or SH(bp.read_bytes())!=row['original']:
                raise ValueError('backup SHA mismatch '+rel)
    print('VERIFY PASS:',len(m['files']),'source/runner/metadata entries, backups intact')

def apply(root=ROOT):
    updates=prepare(root)
    state=root/STATE;state.mkdir()
    m={'tag':TAG,'files':[]};applied=[]
    try:
        for i,(rel,(old,new)) in enumerate(updates.items()):
            back=None
            if old is not None:
                back=f'original_{i:03d}.bin';atomic(state/back,old)
            m['files'].append({'path':rel,'backup':back,'original':SH(old) if old is not None else None,'installed':SH(new)})
        atomic(state/'manifest.json',(json.dumps(m,indent=2)+'\n').encode())
        for rel,(old,new) in updates.items():
            atomic(root/rel,new);applied.append(rel)
        verify(root)
    except BaseException:
        for rel in reversed(applied):
            old=updates[rel][0]
            if old is None:(root/rel).unlink(missing_ok=True)
            else:atomic(root/rel,old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: A/B hot-swaps, 16-color ST7796 text, unlimited F9 host console; images untouched')

def restore(root=ROOT):
    verify(root)
    m=json.loads((root/STATE/'manifest.json').read_bytes())
    for row in reversed(m['files']):
        dest=root/row['path']
        if row['original'] is None:dest.unlink()
        else:atomic(dest,(root/STATE/row['backup']).read_bytes())
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: byte-exact prior source, metadata, host restored')

# The synthetic fixtures reflect the actual repo function anchors but are not
# substituted for the Pico build; probe checks actual user's current sources.
def fixtures(root,have_color_runner=True):
    (root/'src').mkdir();(root/'sd_boot').mkdir();(root/'scripts').mkdir()
    (root/SRC_SD).write_bytes(('''/* BB_DOS622_IPL_V1 */\nstatic FIL bb622_disk;\n    rc = f_lseek(&bb622_disk, (FSIZE_t)lba * 512u);\n    rc = f_read(&bb622_disk, dst, 512u, &got);\n    bb622_disk_open = false;\n    bb622_read_calls = bb622_read_errors = 0;\n/* DOS 6.x floppy boot candidates need the ordinary 1.44MB FAT12 layout. */\n''').encode('utf-8'))
    (root/SRC_SDBOOT).write_bytes(('''static bool bb_b_open;\n    bb_b_open = false;\n    bb_b_number = 0u;\n/* BB_DESCENT_LIVESWAP_V1. Called only by the emulator's INT F6 service. */\n        bb_b_open=true;\n        bb_b_number=selected;\n        printf("[bb-sd-b] LIVE SWITCH B: disk=%u OK\\n",selected);\n''').encode('utf-8'))
    (root/SRC_BIOS).write_bytes(('''/* BB_DOS622_FLOPPY_B_V1 */\nextern bool bb_sd_b_read_sector(uint32_t lba,uint8_t *dst,size_t size);\n    if(fn==0x16u) {bb622_status(c,0u,0u);return true;}\n    if (fn == 0x16u) { bb622_status(c, drive == 0u ? 0u : 0x80u, 0u); return true; }\n''').encode('utf-8'))
    (root/SRC_LIVE).write_bytes(('''/* BB_DOS622_VGA0B_KEYS_V1 */\nstatic void bb_v23_poll_input(void) {\n    /* v33: once video owns the console, this poll is the only reader of the\n       serial port, so Ctrl+] (0x1D) is handled here instead of reaching the\n       guest keyboard queue. */\n''').encode('utf-8'))
    (root/SRC_LCD).write_bytes(('''/* BB_DOS622_LCD_TEXT_V2 */\nstatic uint8_t bb622_text_owns_lcd;\n    for(unsigned x=0;x<COLS;x++) draw_glyph(pixels,COLS*CW,x*CW,0,cells[r][x],0xFFFFu,0x0000u);\n        memset(cells,0,sizeof cells);\n        memset(dirty,1,sizeof dirty);\n            const uint8_t ch=(raw>=32u && raw<=126u) ? raw : (uint8_t)' ';\n            if (cells[y][x] != ch) { cells[y][x]=ch; dirty_row=1u; }\n            printf("[bb622-lcdtext] B800 text shown on LCD; updated-rows=%u\\n",changed_rows);\n''').encode('utf-8'))
    if have_color_runner:
        (root/OLD_HOST).write_bytes((r"""function Write-BbDos622ColorEvent {
    param([string]$Line,[string]$View)
    if ($Line -match '^\[bb622-watch\].*?insns=(\d+)') {
    }
}
function Show-BbDos622ColorFrame {
        if ($script:bbColorActive -and $screenAge -ge 5) {
        }
}
""").encode('utf-8'))
    if have_color_runner:
        (root/SRC_COLOR_RUN).write_bytes(('''param([int]$Seconds=180,[string]$ConsoleView='Screen')\n$quit=$false\n$deadline=(Get-Date).AddSeconds($Seconds)\nwhile((Get-Date) -lt $deadline){\n                    $k=[Console]::ReadKey($true)\n# include bb_dos622_color_host.ps1 -ConsoleView\nWrite-BbDos622ColorConsoleChunk $chunk $ConsoleView\n[System.IO.File]::AppendAllText($log,$chunk)\n''').encode('utf-8'))
    else:
        (root/SRC_BASE_RUN).write_bytes((
            "[CmdletBinding()]\nparam(\n    [int]$Seconds=180,\n    [switch]$PhaseProfile\n)\n"
            "$serial=$null\n$quit=$false\n$deadline=(Get-Date).AddSeconds($Seconds)\n"
            "while((Get-Date) -lt $deadline){\n"
            "    if ($chunk) {\n"
            "            Write-Host -NoNewline $chunk\n"
            "            [System.IO.File]::AppendAllText($log,$chunk)\n"
            "    }\n"
            "    if([Console]::KeyAvailable){\n"
            "                    $k=[Console]::ReadKey($true)\n"
            "                    if($k.Key -eq [ConsoleKey]::Enter){\n"
            "                        $serial.Write(\"`r\")\n"
            "                    }\n"
            "    }\n"
            "        Start-Sleep -Milliseconds 15\n"
            "}\n").encode('utf-8'))

def metadata_regression_test():
    """Real clock-fix record shape and nested SHA propagation; LF/CRLF."""
    for ending in ('LF','CRLF'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            fixtures(root,True)
            sd_path=root/SRC_SD
            initial_sd=sd_path.read_bytes()
            original_src_sha=SH(initial_sd)
            initial_ipl={
                'tag':'BB_DOS622_IPL_V1',
                'files':{'sd_boot/bb_dos622_sd.inc':
                        {'original':None,'installed':original_src_sha}},
            }
            mfpath=root/'.bb_dos622_ipl_v1_state/manifest.json'
            mfpath.parent.mkdir()
            orig_ipl=(json.dumps(initial_ipl,indent=2)+'\n').encode()
            repath=root/CLOCKFIX_REPAIR
            repath.parent.mkdir()
            historical_sd='0'*64
            historical_manifest='1'*64
            orig_repair=(json.dumps({
                'version':1,'sd_before':historical_sd,
                'sd_after':original_src_sha,
                'manifest_before':historical_manifest,
                'manifest_after':SH(orig_ipl),
            },indent=2)+'\n').encode()
            # Another historical parent references the clock-fix record.
            thirdpath=root/'.bb_dos622_parent_test_state/manifest.json'
            thirdpath.parent.mkdir()
            orig_parent=(json.dumps({
                'tag':'TEST_PARENT',
                'files':[{'path':CLOCKFIX_REPAIR,
                          'original':None,'installed':SH(orig_repair)}]
            },indent=2)+'\n').encode()
            records=[mfpath,repath,thirdpath]
            contents=[orig_ipl,orig_repair,orig_parent]
            if ending=='CRLF':
                contents=[x.replace(b'\n',b'\r\n') for x in contents]
                contents[1]=(json.dumps({
                    'version':1,'sd_before':historical_sd,
                    'sd_after':original_src_sha,
                    'manifest_before':historical_manifest,
                    'manifest_after':SH(contents[0]),
                },indent=2)+'\n').encode().replace(b'\n',b'\r\n')
                contents[2]=(json.dumps({
                    'tag':'TEST_PARENT',
                    'files':[{'path':CLOCKFIX_REPAIR,
                              'original':None,'installed':SH(contents[1])}]
                },indent=2)+'\n').encode().replace(b'\n',b'\r\n')
                for f in [sd_path]:
                    v=f.read_bytes().replace(b'\r\n',b'\n')
                    f.write_bytes(v.replace(b'\n',b'\r\n'))
                # Recompute source SHA used in the clock-fix record, too.
                original_src_sha=SH(sd_path.read_bytes())
                doc=json.loads(contents[1]);doc['sd_after']=original_src_sha
                contents[1]=(json.dumps(doc,indent=2)+'\n').encode().replace(b'\n',b'\r\n')
                doc=json.loads(contents[0]);doc['files']['sd_boot/bb_dos622_sd.inc']['installed']=original_src_sha
                contents[0]=(json.dumps(doc,indent=2)+'\n').encode().replace(b'\n',b'\r\n')
                doc=json.loads(contents[1]);doc['manifest_after']=SH(contents[0])
                contents[1]=(json.dumps(doc,indent=2)+'\n').encode().replace(b'\n',b'\r\n')
                doc=json.loads(contents[2]);doc['files'][0]['installed']=SH(contents[1])
                contents[2]=(json.dumps(doc,indent=2)+'\n').encode().replace(b'\n',b'\r\n')
            for path,blob in zip(records,contents):path.write_bytes(blob)
            originals={f:(root/f).read_bytes() for f in [*SOURCES,SRC_COLOR_RUN,OLD_HOST]}
            originals.update({str(x.relative_to(root)):x.read_bytes() for x in records})
            saved_active=chain.active_metadata
            try:
                chain.active_metadata=lambda workspace: {str(x.relative_to(root)):x.read_bytes() for x in records}
                updates=prepare(root,False)
                paths=set(updates)
                assert str(repath.relative_to(root)) in paths
                assert str(mfpath.relative_to(root)) in paths
                assert str(thirdpath.relative_to(root)) in paths
                apply(root)
                verify(root)
                fixed=json.loads(repath.read_bytes())
                assert fixed['sd_before']==historical_sd
                assert fixed['manifest_before']==historical_manifest
                assert fixed['sd_after']==SH(sd_path.read_bytes())
                assert fixed['manifest_after']==SH(mfpath.read_bytes())
                parent=json.loads(thirdpath.read_bytes())
                assert parent['files'][0]['installed']==SH(repath.read_bytes())
                restore(root)
            finally:
                chain.active_metadata=saved_active
            assert all((root/rel).read_bytes()==val for rel,val in originals.items())
            assert not (root/STATE).exists()
            print('SELFTEST',ending,'SD clockfix sd_after/manifest_after cascade + rollback PASS')
    # Unknown checksum schemas must STILL cause probe refusal.
    try:
        update_known_metadata(
            b'{"unexpected_after":"'+b'2'*64+b'"}',{'2'*64:'3'*64},
            '.bb_dos622_other_state/repair.json')
    except ValueError as exc:
        assert 'Unknown current-SHA key' in str(exc)
    else:raise AssertionError('Unknown checksum key was silently accepted')
    print('SELFTEST unknown checksum key refusal PASS')

def selftest():
    for have_previous in (True,False):
        for ending in ('LF','CRLF'):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);fixtures(root,have_previous)
                files=[*SOURCES]
                if have_previous:files += [SRC_COLOR_RUN,OLD_HOST]
                else:files += [SRC_BASE_RUN]
                if ending=='CRLF':
                    for rel in files:
                        path=root/rel
                        raw=path.read_bytes().replace(b'\r\n',b'\n').replace(b'\r',b'\n')
                        path.write_bytes(raw.replace(b'\n',b'\r\n'))
                originals={r:(root/r).read_bytes() for r in files}
                original_active=chain.active_metadata
                try:
                    chain.active_metadata=lambda workspace:{}
                    apply(root);verify(root)
                    for rel in SOURCES:
                        assert TAG.encode() in (root/rel).read_bytes()
                    runner=(root/NEW_RUN).read_text(encoding='utf-8-sig')
                    helper=(root/NEW_HOST).read_text(encoding='utf-8-sig')
                    assert 'while($Seconds -le 0' in runner
                    assert "if($k.Key -eq [ConsoleKey]::F9)" in runner
                    assert 'Write-BbDos622ColorConsoleChunk' in runner
                    assert '[System.IO.File]::AppendAllText($log,$chunk)' in runner
                    assert 'bbColorSwapAck' in helper
                    restore(root)
                finally:chain.active_metadata=original_active
                assert all((root/r).read_bytes()==value for r,value in originals.items())
                assert not (root/NEW_RUN).exists() and not (root/NEW_HOST).exists()
                label='existing color runner' if have_previous else 'base-runner fallback'
                print('SELFTEST',ending,label,'PASS exact rollback, host F9, no timeout')
    metadata_regression_test()
    assert 'candidate = (bb622_swap_active==&bb622_disk)' in SD_A_FUNC
    print('SELFTEST PASS: real Pico hardware and DOS floppy switching remain untested')

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['selftest','probe','apply','verify','restore'])
    args=ap.parse_args()
    try:
        {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore}[args.command]()
    except (ValueError,RuntimeError,AssertionError,OSError) as e:
        print('ERROR:',e);sys.exit(1)
