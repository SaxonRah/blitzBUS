/* blitzBUS v0.4: 80x25 DOS COM mirror + live diagnostic HUD.
 * Panel: 480x320 ST7796S. MADCTL=0xE8 supplied by CMake (MicroConsole default).
 * COM remains the input and debug transport; framebuffer is only a mirror.
 */
#include "bb_lcd_console.h"
#include "bb_vga.h"
#include "mr_pico_ili9341.h"
#include "gfx_font5x7.h"
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/spi.h"
#include <stdio.h>
#include <string.h>
#define COLS 80u
#define ROWS 25u
#define CW 6u
#define CH 8u
#define TEXT_H (ROWS*CH)
#define HUD_Y TEXT_H
#define HUD_H (320u-HUD_Y)
static mr_pico_ili9341_t lcd = {
    .spi=MR_LCD_SPI, .pin_miso=MR_LCD_PIN_MISO, .pin_cs=MR_LCD_PIN_CS,
    .pin_sck=MR_LCD_PIN_SCK, .pin_mosi=MR_LCD_PIN_MOSI,
    .pin_rst=MR_LCD_PIN_RST, .pin_dc=MR_LCD_PIN_DC,
    .spi_baud_hz=MR_LCD_SPI_BAUD
};
static uint8_t cells[ROWS][COLS];
static uint8_t dirty[ROWS];
/* One 480x8 RGB565 strip, static rather than stack. */
static uint16_t pixels[COLS*CW*CH];
static unsigned row, col;
static unsigned long characters, paint_rows, batches;
static uint32_t next_status_ms;
static int active;
/* BB_DOS622_SCREEN_CLEAR_V1: DOS6 has a clean dedicated 80x25 LCD surface. */
static uint8_t bb622_text_owns_lcd;
/* BB_DOS622_SWAP_LCD_V2: VGA text attributes in PSRAM, not RP2350 SRAM.
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

static void draw_glyph(uint16_t *dst,unsigned pitch,unsigned xx,unsigned yy,unsigned char c,uint16_t fg,uint16_t bg){
    const uint8_t *g=gfx_font5x7[(c>=32 && c<=127 ? c: '?')-32];
    for(unsigned gy=0;gy<8;gy++) for(unsigned gx=0;gx<6;gx++)
        dst[(yy+gy)*pitch+xx+gx]=(gy<7 && gx<5 && (g[gx]&(1u<<gy)))?fg:bg;
}
static void draw_row(unsigned r){
    for(unsigned x=0;x<COLS;x++) {
        if(bb622_text_owns_lcd)bb622_lcd_draw_cell(pixels,COLS*CW,x*CW,
            cells[r][x],bb622_lcd_attr[r][x]);
        else draw_glyph(pixels,COLS*CW,x*CW,0,cells[r][x],0xFFFFu,0x0000u);
    }
    mr_pico_ili9341_flush(NULL,0,(int)(r*CH),480,CH,pixels,&lcd);
    paint_rows++;
}
static void status_row(unsigned index,const char *msg){
    memset(pixels,0,sizeof pixels);
    unsigned len=(unsigned)strlen(msg);
    if(len>COLS)len=COLS;
    for(unsigned x=0;x<len;x++)draw_glyph(pixels,COLS*CW,x*CW,0,(unsigned char)msg[x],0x07FFu,0x0000u);
    mr_pico_ili9341_flush(NULL,0,(int)(HUD_Y+index*CH),480,CH,pixels,&lcd);
}
static void status_update(void){
    char msg[81];
    uint32_t ms=to_ms_since_boot(get_absolute_time());
    status_row(0,"blitzBUS  |  RP2350 / ST7796S  |  SERIAL COM CONTROL");
    status_row(1,"CPU: microDOS AOT + interpreter  |  blitz86 DOS backend: NOT ACTIVE");
    snprintf(msg,sizeof msg,"Uptime %lus  |  DOS text 80x25  |  LCD 480x320 RGB565",(unsigned long)(ms/1000u));status_row(2,msg);
    snprintf(msg,sizeof msg,"Console chars %lu  |  rendered text rows %lu  |  flushes %lu",characters,paint_rows,batches);status_row(3,msg);
    status_row(4,"Memory: guest 1 MiB PSRAM / conventional 640 KiB (configured)");
    status_row(5,"USB: serial input enabled  |  audio: not yet integrated");
    status_row(6,"DOS/BIOS: microDOS  |  real blitz86 integration pending");
    status_row(7,"Controls: COM keyboard  |  Ctrl+] performance log (serial)");
    for(unsigned y=8;y<HUD_H/CH;y++){memset(pixels,0,sizeof pixels);mr_pico_ili9341_flush(NULL,0,(int)(HUD_Y+y*CH),480,CH,pixels,&lcd);}
}
void bb_lcd_console_init(void){
    memset(cells,' ',sizeof cells);memset(dirty,1,sizeof dirty);
    puts("[blitzBUS] LCD SPI init begin");fflush(stdout);
    printf("[bb-v29-clock] pre-init clk-sys=%lu clk-peri=%lu requested-spi=%lu\n",
        (unsigned long)clock_get_hz(clk_sys),
        (unsigned long)clock_get_hz(clk_peri),
        (unsigned long)lcd.spi_baud_hz); fflush(stdout);
    /* v30: clk_sys is already 300 MHz with the project's PSRAM timing.
       Reparent ONLY clk_peri to clk_sys and divide to 150 MHz.
       USB's independent 48 MHz clock and the 300 MHz CPU clock are untouched.
       Use BB_LCD_PERI_HZ=48000000 at build time for the previous behavior.
       All clock adjustments occur before any SPI or DMA initialization. */
#if defined(BB_LCD_PERI_SYSDIV) && BB_LCD_PERI_SYSDIV > 0
    {   /* BB_CLK400_V1: clk_peri = clk_sys / N with an exact integer divider
           (no fractional jitter on the LCD and SD SPI clocks), e.g. 400/3. */
        const uint32_t sys_hz=clock_get_hz(clk_sys);
        const uint32_t want=sys_hz/(uint32_t)BB_LCD_PERI_SYSDIV;
        const bool ok=clock_configure(clk_peri,0u,
                CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS,
                sys_hz,want);
        printf("[bb-clk400] clk-peri = clk-sys/%u: sys=%lu want=%lu result=%s actual=%lu\n",
            (unsigned)BB_LCD_PERI_SYSDIV,(unsigned long)sys_hz,(unsigned long)want,
            ok?"OK":"FALLBACK",(unsigned long)clock_get_hz(clk_peri));fflush(stdout);
        if (!ok) {
            const bool fallback=clock_configure(clk_peri,0u,
                CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS,
                sys_hz,48000000u);
            printf("[bb-v30-clock] fallback-48 result=%s actual=%lu\n",
                fallback?"OK":"FAILED",(unsigned long)clock_get_hz(clk_peri));
            fflush(stdout);
        }
    }
#elif BB_LCD_PERI_HZ == 150000000u
    {
        const uint32_t sys_hz=clock_get_hz(clk_sys);
        const bool ok=(sys_hz >= 150000000u) &&
            clock_configure(clk_peri,0u,
                CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS,
                sys_hz,150000000u);
        printf("[bb-v30-clock] clk-peri-150 request sys=%lu result=%s actual=%lu\n",
            (unsigned long)sys_hz, ok?"OK":"FALLBACK",
            (unsigned long)clock_get_hz(clk_peri));fflush(stdout);
        if (!ok || clock_get_hz(clk_peri)!=150000000u) {
            /* RP2350 clk_peri has no CLK_USB AUXSRC selector.
               Recover from the known 300 MHz clk_sys source instead.
               300 MHz / 6.25 = 48 MHz (fractional divider). */
            const bool fallback=clock_configure(clk_peri,0u,
                CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS,
                sys_hz,48000000u);
            printf("[bb-v30-clock] fallback-48 result=%s actual=%lu\n",
                fallback?"OK":"FAILED",(unsigned long)clock_get_hz(clk_peri));
            fflush(stdout);
        }
    }
#else
    printf("[bb-v30-clock] 48 MHz compatibility mode clk-peri=%lu\n",
        (unsigned long)clock_get_hz(clk_peri));fflush(stdout);
#endif
    /* SPI cannot outrun its peripheral clock.  Reject unsafe overclocking
       before configuring or starting asynchronous transfers. */
    if (lcd.spi_baud_hz > clock_get_hz(clk_peri)/2u) {
        printf("[bb-v29-clock] REJECT requested=%lu: clk-peri=%lu, max-safe=%lu; using divider-2 rate\n",
            (unsigned long)lcd.spi_baud_hz,
            (unsigned long)clock_get_hz(clk_peri),
            (unsigned long)(clock_get_hz(clk_peri)/2u)); fflush(stdout);
        lcd.spi_baud_hz=clock_get_hz(clk_peri)/2u;
    }
    mr_pico_ili9341_init(&lcd);
    printf("[bb-v29-clock] post-init clk-peri=%lu spi-actual=%lu prescale=%lu scr=%lu\n",
        (unsigned long)clock_get_hz(clk_peri),
        (unsigned long)spi_get_baudrate(lcd.spi),
        (unsigned long)spi_get_hw(lcd.spi)->cpsr,
        (unsigned long)((spi_get_hw(lcd.spi)->cr0 >> 8)&255u));
    puts("[blitzBUS] LCD SPI init PASS");fflush(stdout);
    puts("[blitzBUS] LCD panel init begin (MADCTL=0xE8)");fflush(stdout);
    mr_pico_ili9341_panel_init(&lcd);
    printf("[bb-v29-clock] post-panel clk-peri=%lu spi-actual=%lu driver-spi=%lu\n",
        (unsigned long)clock_get_hz(clk_peri),
        (unsigned long)spi_get_baudrate(lcd.spi),
        (unsigned long)lcd.spi_baud_hz);
    puts("[blitzBUS] LCD panel init PASS");fflush(stdout);
    puts("[blitzBUS] LCD clear begin");fflush(stdout);
    mr_pico_ili9341_fill_screen(&lcd,0x0000u,480,320);puts("[blitzBUS] LCD clear PASS");fflush(stdout);
    row=col=0;characters=paint_rows=batches=0;active=1;next_status_ms=0;bb622_text_owns_lcd=0u;
    bb_lcd_console_flush();
}
static void newline(void){
    col=0;if(row+1<ROWS){row++;return;}
    memmove(cells[0],cells[1],(ROWS-1u)*COLS);memset(cells[ROWS-1u],' ',COLS);
    memset(dirty,1,sizeof dirty);
}
void bb_lcd_console_write(const uint8_t *data,size_t count){
    if(!active)return;
    for(size_t i=0;i<count;i++){
        unsigned c=data[i];characters++;
        if(c=='\r'){col=0;continue;}
        if(c=='\n'){newline();continue;}
        if(c=='\b'){if(col)col--;cells[row][col]=' ';dirty[row]=1;continue;}
        if(c=='\t'){unsigned n=8u-(col&7u);while(n--){cells[row][col]=' ';dirty[row]=1;if(++col>=COLS)newline();}continue;}
        if(c<32)continue;
        if(col>=COLS)newline();
        cells[row][col]=(uint8_t)(c<=127?c:'?');dirty[row]=1;
        if(++col>=COLS)newline();
    }
}
void bb_lcd_console_flush(void){
    if(!active)return;
    batches++;
    for(unsigned r=0;r<ROWS;r++)if(dirty[r]){draw_row(r);dirty[r]=0;}
    uint32_t ms=to_ms_since_boot(get_absolute_time());
    if(!bb622_text_owns_lcd && (int32_t)(ms-next_status_ms)>=0){status_update();next_status_ms=ms+1000u;}
}

/* BB_DOS622_LCD_TEXT_V2: LCD text-mode mirror from the real guest B800h RAM.
 * This is an LCD observer only. The DOS guest, text BIOS, and DOS2 remain unchanged.
 * Mirror runs at most 12.5 Hz, has no allocations, and flushes only changed rows.
 * It operates on the existing 80x25/6x8 font and does not reset the VGA device. */
void bb622_lcd_text_mirror(const uint8_t *guest)
{
    static uint32_t last_ms;
    static uint8_t sampled;
    static uint8_t first_change_logged;
    if (!active || !guest) return;
    if (!bb622_text_owns_lcd) {
        /* DOS2 diagnostic HUD occupied the lower 120 physical pixels.
           Clear the WHOLE panel exactly once at DOS6 text-mode takeover.
           Invalidate every cached text cell so even spaces are repainted.
           The DOS2/HUD path remains unchanged outside the DOS6 mirror. */
        bb622_text_owns_lcd=1u;
        mr_pico_ili9341_fill_screen(&lcd,0x0000u,480,320);
        memset(cells,0,sizeof cells);
        memset(bb622_lcd_attr,0x07,sizeof bb622_lcd_attr);
        memset(dirty,1,sizeof dirty);
        puts("[bb622-lcdclear] DOS6 text LCD takeover, full 480x320 clear; DOS2 HUD disabled");
        fflush(stdout);
    }
    const uint32_t now_ms=to_ms_since_boot(get_absolute_time());
    if (sampled && (uint32_t)(now_ms-last_ms) < 80u) return;
    sampled=1u;
    last_ms=now_ms;
    const uint8_t *const text=guest+0xB8000u;
    unsigned changed_rows=0;
    for (unsigned y=0; y<ROWS; ++y) {
        unsigned dirty_row=0;
        for (unsigned x=0; x<COLS; ++x) {
            const uint8_t raw=text[(y*COLS+x)*2u];
            const uint8_t ch=(raw>=32u) ? raw : (uint8_t)' ';
            const uint8_t attr=text[(y*COLS+x)*2u+1u];
            if (cells[y][x]!=ch || bb622_lcd_attr[y][x]!=attr) {
                cells[y][x]=ch;bb622_lcd_attr[y][x]=attr;dirty_row=1u;
            }
        }
        if (dirty_row) { dirty[y]=1u; ++changed_rows; }
    }
    if (changed_rows) {
        bb_lcd_console_flush();
        if (!first_change_logged) {
            first_change_logged=1u;
            printf("[bb622-lcdcolor] 16-color VGA B800 text on LCD; updated-rows=%u\n",changed_rows);
            fflush(stdout);
        }
    }
}

/* v27: MicroRender's DMA presenter on core 1.
 * Core 0 NEVER converts or transfers video while VGA mode 13h is active.
 * Only the presenter core owns the LCD SPI peripheral during VGA.
 * DMA sends tile A while core 1 converts tile B.  After DMA completes,
 * the buffers swap; neither buffer is modified while owned by DMA.
 * Guest VGA memory may change during presentation (ordinary VGA tearing).
 */
#define BB_V27_W 480u
#define BB_V27_H 300u
/* v32: 0 = exact full-frame v31 path; 1 = true alternate scanline fields.
   Interlaced: one LCD scanline per window; each parity updates 150 rows.
   Two fields restore all 300 rows. Avoid counting field FPS as full-frame FPS. */
#ifndef BB_LCD_LACE
#define BB_LCD_LACE 0
#endif
#if BB_LCD_LACE
#define BB_V27_TILE_H 1u
#define BB_V27_TILES (BB_V27_H / 2u)
#define BB_V32_DEST_Y(i,parity) ((parity) + (i)*2u)
#else
#define BB_V27_TILE_H 30u
#define BB_V27_TILES (BB_V27_H / BB_V27_TILE_H)
#define BB_V32_DEST_Y(i,parity) ((i)*BB_V27_TILE_H)
#endif
static uint16_t bb_v27_tiles[2][BB_V27_W * BB_V27_TILE_H];
static volatile uint32_t bb_v27_request;
volatile uint32_t bb_lcd_paused;      /* v38: set from bb_live (Ctrl+P) */
static volatile uint32_t bb_v27_busy;
static volatile uint32_t bb_v27_parked;
static uint32_t bb_v27_started;
static uint8_t bb_v27_was_vga;
static volatile uint32_t bb_v27_frames;
static volatile uint32_t bb_v27_strips;
static unsigned bb_v32_field_parity;
/* BB_V93_GAME_FPS: Descent's real frame rate. Core 1 hashes every guest
 * framebuffer row it converts; a field whose hash differs from the previous
 * field of the same parity shows a new picture. Counted per parity; the
 * report uses the larger count, so a game frame is never counted twice and a
 * change seen by only one parity still counts. = game frames/s, exact while
 * the game stays below the LCD's full-frame rate (15/s interlaced). Core 1
 * writes, core 0 only reads the counters. */
static uint32_t bb_v93_hash;                       /* core 1: current field */
static uint32_t bb_v93_last[2];                    /* core 1: last hash per parity */
static volatile uint32_t bb_v93_changed[2];
static uint32_t bb_v93_report_changed[2];
static inline void bb_v93_row(const uint8_t *row)
{
    const uint32_t *w = (const uint32_t *)(const void *)row;
    uint32_t h = bb_v93_hash;
    for (unsigned k = 0u; k < 80u; ++k) h = (h ^ w[k]) * 0x01000193u;
    bb_v93_hash = h;
}
/* Core 1 owns these monotonically increasing counters; Core 0 only reads. */
static volatile uint32_t bb_v29_stage; /* 0 idle, 1 convert, 2 DMA begin, 3 DMA wait, 4 completed */
static volatile uint32_t bb_v29_heartbeat_us;
static volatile uint32_t bb_v28_convert_us;
static volatile uint32_t bb_v28_dma_us;
static volatile uint32_t bb_v28_frame_us;
static volatile uint32_t bb_v28_max_frame_us;
static volatile uint32_t bb_v28_last_frame_us;
static uint32_t bb_v28_report_ms;
static uint32_t bb_v28_report_frames;
static uint32_t bb_v28_report_strips;
static uint32_t bb_v28_report_convert;
static uint32_t bb_v28_report_dma;
static uint32_t bb_v28_report_frame;
static uint32_t bb_v28_poll;


/* v31: exact 320x200 -> 480x300 3:2 nearest-neighbour expansion.
 * Every 3 destination scanlines are source rows A, A, B. Generate A once,
 * duplicate its expanded RGB565 row using memcpy, then generate B. All
 * 30-row tile origins are multiples of three; no division/modulo per row.
 * Preserve the existing color ordering, including palette changes.
 */
static inline void bb_v31_expand_row(const uint8_t *src,
                                     const uint16_t *pal,
                                     uint16_t *restrict dst) {
    for (unsigned x=0u; x<320u; x+=2u) {
        const uint16_t a=pal[src[x]];
        const uint16_t b=pal[src[x+1u]];
        dst[0]=a; dst[1]=a; dst[2]=b;
        dst+=3;
    }
}
#if BB_LCD_LACE
/* Display coordinates y=0..299 correspond to 320x200 mode 13h.
   floor(y*2/3) is the exact nearest-neighbour v31 mapping A,A,B. */
static void bb_v27_convert(unsigned top, uint16_t *dst) {
    const uint8_t *fb=bb_vga_framebuffer();
    const uint16_t *pal=bb_vga_palette565();
    if (!fb || !pal) {
        memset(dst,0,BB_V27_W*sizeof(*dst));
        return;
    }
    const unsigned src_y=(top*2u)/3u;
    bb_v93_row(fb+src_y*320u);
    bb_v31_expand_row(fb+src_y*320u,pal,dst);
}
#else
static void bb_v27_convert(unsigned top, uint16_t *dst) {
    const uint8_t *fb=bb_vga_framebuffer();
    const uint16_t *pal=bb_vga_palette565();
    if (!fb || !pal) {
        memset(dst,0,BB_V27_W*BB_V27_TILE_H*sizeof(*dst));
        return;
    }
    const unsigned first_src=(top/3u)*2u;
    for (unsigned y=0u;y<BB_V27_TILE_H;y+=3u) {
        const unsigned src_y=first_src+(y/3u)*2u;
        uint16_t *out=dst+y*BB_V27_W;
        bb_v93_row(fb+src_y*320u);
        bb_v31_expand_row(fb+src_y*320u,pal,out);
        memcpy(out+BB_V27_W,out,BB_V27_W*sizeof(*out));
        bb_v93_row(fb+(src_y+1u)*320u);
        bb_v31_expand_row(fb+(src_y+1u)*320u,pal,out+2u*BB_V27_W);
    }
}

#endif

/* BB_STAGE5D_LCD_PACER_V1 */
/* LCD presenter runs on core 1. For interlace this is FIELDS/sec.
 * 0 means original unlimited; default 30 fields/s (~15 full screens/s).
 * In non-interlaced mode this is full FRAMES/sec. */
#ifndef BB_STAGE5D_VGA_MAX_FIELD_HZ
#define BB_STAGE5D_VGA_MAX_FIELD_HZ 30u
#endif
#if BB_STAGE5D_VGA_MAX_FIELD_HZ > 120u
#error "Stage5D LCD max field Hz must be 0..120"
#endif

/* BB_CORE1_SRAM_WAIT_V1: core 1 waits in SRAM. sleep_us() on core 1 is woken
 * by the default alarm pool, whose interrupt runs on CORE 0 (~300 interrupts/s
 * from the pacer, handler in flash); SDK busy-waits and the ILI9341 wait loops
 * run from flash, and the Cortex-M33 has no instruction cache, so a spinning
 * core 1 keeps fetching through the XIP interface core 0 needs for PSRAM code
 * and data. These loops read the same registers from SRAM. */
#ifndef BB_CORE1_SRAM_WAIT
#define BB_CORE1_SRAM_WAIT 1
#endif

/* BB_AUDIO_V1: core 1 plays the guest's Sound Blaster PCM through MicroWave's
 * PIO I2S program (MAX98357A wiring as in microconsole: BCLK GP10, LRCLK GP11,
 * DATA GP20; PIO1 SM0). A 4 KiB ring (1024 stereo frames) in PSRAM, written
 * and read through the UNCACHED alias, is streamed endlessly by one DMA
 * channel (read-ring wrap, no interrupts). Core 1 keeps ~23 ms queued ahead of
 * the DMA from its SRAM wait loops; the producer resamples the card's 8-bit
 * samples (bb_snd_pcm_*, exported by bb_live.c) to BB_AUDIO_RATE with linear
 * interpolation. Requires BB_CORE1_SRAM_WAIT. BB_AUDIO=0: none of this. */
#ifndef BB_AUDIO
#define BB_AUDIO 1
#endif
#if BB_AUDIO && !BB_CORE1_SRAM_WAIT
#undef BB_AUDIO
#define BB_AUDIO 0
#endif
#if BB_AUDIO
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "bb_mw_i2s.pio.h"
#ifndef BB_AUDIO_RATE
#define BB_AUDIO_RATE 22050u
#endif
#ifndef BB_AUDIO_PIN_BCLK
#define BB_AUDIO_PIN_BCLK 10u            /* LRCLK is BCLK + 1 */
#endif
#ifndef BB_AUDIO_PIN_DATA
#define BB_AUDIO_PIN_DATA 20u
#endif
#ifndef BB_AUDIO_PIO
#define BB_AUDIO_PIO pio1
#endif
#ifndef BB_AUDIO_SM
#define BB_AUDIO_SM 0u
#endif
#ifndef BB_AUDIO_VOLUME
#define BB_AUDIO_VOLUME 192u             /* of 256 */
#endif
#define BB_AU_FRAMES 1024u               /* ring: 1024 frames x 4 bytes = 4 KiB */
#define BB_AU_RING_BITS 12u
#define BB_AU_LEAD 512u                  /* keep ~23 ms queued ahead of the DMA */
#define BB_AU_CHUNK 64u                  /* refill granularity */
extern uint32_t bb_snd_pcm_read(uint8_t *dst, uint32_t n);
extern uint32_t bb_snd_pcm_avail(void);
extern uint32_t bb_snd_pcm_rate(void);
extern void *bb_meta_calloc(size_t n, size_t size);
static volatile uint32_t *bb_au_ring;
static int bb_au_dma = -1;
static uint32_t bb_au_w, bb_au_phase, bb_au_rate, bb_au_step;
static int32_t bb_au_prev, bb_au_cur;
static uint8_t bb_au_playing, bb_au_in[64];
static uint32_t bb_au_in_n, bb_au_in_i;
/* status, frames out, pcm bytes in, dma underruns, starved, rate,
 * ring check (0 = ok; uncached read-back mismatches + 1000 x cached read-back mismatches),
 * peak |output| since the last report, non-silent input bytes since the last report */
static volatile unsigned long bb_au_n[9];
static uint32_t *bb_au_ring_cached;              /* BB_AUDIO_V2: same memory, cached alias (self-check only) */
static uint32_t bb_au_tone_left, bb_au_tone_phase;   /* BB_AUDIO_V2: start-up test tone */

/* frames the DMA has not yet read, from SRAM (no flash fetch while waiting) */
static inline __attribute__((always_inline)) uint32_t bb_au_ahead(void)
{
    const uint32_t r = (((uint32_t)dma_hw->ch[bb_au_dma].read_addr - (uint32_t)(uintptr_t)bb_au_ring) >> 2) & (BB_AU_FRAMES - 1u);
    return (bb_au_w - r) & (BB_AU_FRAMES - 1u);
}
static inline __attribute__((always_inline)) int bb_au_need(void)
{
    if (bb_au_dma < 0) return 0;
    const uint32_t a = bb_au_ahead();
    return a + BB_AU_CHUNK <= BB_AU_LEAD || a > BB_AU_LEAD + 128u;
}
static int bb_au_byte(uint8_t *b)
{
    if (bb_au_in_i == bb_au_in_n) {
        bb_au_in_n = bb_snd_pcm_read(bb_au_in, sizeof bb_au_in); bb_au_in_i = 0;
        bb_au_n[2] += bb_au_in_n;
        if (!bb_au_in_n) return 0;
    }
    *b = bb_au_in[bb_au_in_i++];
    if (*b < 126u || *b > 130u) ++bb_au_n[8];     /* BB_AUDIO_V2 level meter */
    return 1;
}
static int32_t bb_au_next_sample(void)
{
    if (!bb_au_playing) {
        if (bb_au_in_i == bb_au_in_n && bb_snd_pcm_avail() < 512u) return 0;   /* ~46 ms pre-buffer */
        bb_au_playing = 1; bb_au_phase = 0; bb_au_prev = bb_au_cur = 0;
    }
    bb_au_phase += bb_au_step;
    while (bb_au_phase >= 65536u) {
        uint8_t b;
        bb_au_phase -= 65536u;
        if (!bb_au_byte(&b)) { bb_au_playing = 0; ++bb_au_n[4]; bb_au_prev = bb_au_cur = 0; return 0; }
        bb_au_prev = bb_au_cur; bb_au_cur = ((int32_t)b - 128) * 256;
    }
    const int32_t v = bb_au_prev + (((bb_au_cur - bb_au_prev) * (int32_t)(bb_au_phase >> 1)) >> 15);
    return (v * (int32_t)BB_AUDIO_VOLUME) >> 8;
}
/* producer (flash): fill the ring up to BB_AU_LEAD frames ahead of the DMA */
static void __noinline bb_au_pump(void)
{
    if (bb_au_dma < 0) return;
    const uint32_t rate = bb_snd_pcm_rate();
    if (rate != bb_au_rate) { bb_au_rate = rate; bb_au_step = (uint32_t)(((uint64_t)rate << 16) / BB_AUDIO_RATE); bb_au_n[5] = rate; }
    uint32_t ahead = bb_au_ahead();
    if (ahead > BB_AU_LEAD + 128u) {                  /* the DMA overtook the writer: resynchronise */
        ++bb_au_n[3];
        const uint32_t r = (bb_au_w - ahead) & (BB_AU_FRAMES - 1u);
        bb_au_w = (r + BB_AU_CHUNK) & (BB_AU_FRAMES - 1u);
        ahead = BB_AU_CHUNK;
    }
    for (uint32_t todo = ahead < BB_AU_LEAD ? BB_AU_LEAD - ahead : 0u; todo; --todo) {
        int32_t s = bb_au_next_sample();
        if (bb_au_tone_left) {                        /* BB_AUDIO_V2: 1 s, 880 Hz triangle at start-up */
            --bb_au_tone_left;
            bb_au_tone_phase += (uint32_t)(((uint64_t)880u << 32) / BB_AUDIO_RATE);
            const int32_t tri = (int32_t)(bb_au_tone_phase >> 16);          /* 0..65535 */
            s += ((tri < 32768 ? tri : 65535 - tri) - 16384) / 2;           /* +-8192 */
            if (s > 32767) s = 32767;
            if (s < -32768) s = -32768;
        }
        { const unsigned long m = (unsigned long)(s < 0 ? -s : s); if (m > bb_au_n[7]) bb_au_n[7] = m; }
        bb_au_ring[bb_au_w] = ((uint32_t)(uint16_t)s << 16) | (uint16_t)s;   /* left | right */
        bb_au_w = (bb_au_w + 1u) & (BB_AU_FRAMES - 1u);
        ++bb_au_n[1];
    }
}
/* BB_AUDIO_V3: XIP cache maintenance by address (RP2350; 8-byte lines): op 3
 * cleans (writes back a dirty line), op 2 invalidates. */
static void bb_au_cache_drop(uintptr_t cached_addr, uint32_t bytes, int clean_first)
{
    const uintptr_t off0 = (cached_addr - 0x10000000u) & ~(uintptr_t)7u;
    const uintptr_t end = cached_addr - 0x10000000u + bytes;
    if (clean_first)
        for (uintptr_t o = off0; o < end; o += 8u) *(volatile uint8_t *)(0x18000000u + o + 3u) = 0;
    for (uintptr_t o = off0; o < end; o += 8u) *(volatile uint8_t *)(0x18000000u + o + 2u) = 0;
    __asm volatile ("dsb 0xF\n\tisb 0xF" ::: "memory");
}
/* BB_AUDIO_V2: core 0, before core 1 starts - bb_meta_calloc is core 0's allocator.
 * Self-check: a pattern written through the uncached alias must read back
 * through both aliases (otherwise the DMA would stream something else). */
static void bb_au_prepare(void)
{
    uint8_t *raw = (uint8_t *)bb_meta_calloc(2u * BB_AU_FRAMES * 4u, 1u);
    if (!raw) { bb_au_n[0] = 4u; return; }
    uintptr_t a = ((uintptr_t)raw + (BB_AU_FRAMES * 4u - 1u)) & ~(uintptr_t)(BB_AU_FRAMES * 4u - 1u);
    bb_au_ring_cached = (uint32_t *)a;
    const int psram = a >= 0x11000000u && a < 0x12000000u;
    if (psram) a += 0x04000000u;                                    /* PSRAM: uncached alias */
    bb_au_ring = (volatile uint32_t *)a;
    /* BB_AUDIO_V3: bb_meta_calloc zeroed this memory through the CACHED alias,
     * which can leave (dirty) lines in the XIP cache; evicted later they would
     * overwrite what core 1 writes through the uncached alias. Clean, then
     * invalidate, every line of the range (the SDK's xip_cache_maintain method). */
    if (psram) bb_au_cache_drop((uintptr_t)raw, 2u * BB_AU_FRAMES * 4u, 1);
    unsigned long bad_u = 0, bad_c = 0;
    for (uint32_t i = 0; i < BB_AU_FRAMES; ++i) bb_au_ring[i] = 0x9E3779B1u * (i + 1u);
    for (uint32_t i = 0; i < BB_AU_FRAMES; ++i) if (bb_au_ring[i] != 0x9E3779B1u * (i + 1u)) ++bad_u;
    if (psram) bb_au_cache_drop((uintptr_t)bb_au_ring_cached, BB_AU_FRAMES * 4u, 0);
    for (uint32_t i = 0; i < BB_AU_FRAMES; ++i)
        if (((volatile uint32_t *)bb_au_ring_cached)[i] != 0x9E3779B1u * (i + 1u)) ++bad_c;
    if (psram) bb_au_cache_drop((uintptr_t)bb_au_ring_cached, BB_AU_FRAMES * 4u, 0);   /* nothing of it stays cached */
    bb_au_n[6] = bad_u + 1000u * bad_c;
    for (uint32_t i = 0; i < BB_AU_FRAMES; ++i) bb_au_ring[i] = 0u;
}
/* called once on core 1; any failure leaves audio off and the LCD unaffected */
static void bb_au_start(void)
{
    PIO pio = BB_AUDIO_PIO;
    if (!bb_au_ring) return;                          /* bb_au_prepare failed (status 4) */
    if (pio_sm_is_claimed(pio, BB_AUDIO_SM) || !pio_can_add_program(pio, &mw_i2s_program)) { bb_au_n[0] = 2u; return; }
    pio_sm_claim(pio, BB_AUDIO_SM);
    const uint off = pio_add_program(pio, &mw_i2s_program);
    pio_gpio_init(pio, BB_AUDIO_PIN_DATA);
    pio_gpio_init(pio, BB_AUDIO_PIN_BCLK);
    pio_gpio_init(pio, BB_AUDIO_PIN_BCLK + 1u);
    mw_i2s_program_init(pio, BB_AUDIO_SM, off, BB_AUDIO_PIN_DATA, BB_AUDIO_PIN_BCLK);
    const uint32_t sys_hz = clock_get_hz(clk_sys);
    const uint32_t div256 = (uint32_t)((((uint64_t)sys_hz * 4u) + BB_AUDIO_RATE / 2u) / BB_AUDIO_RATE);
    pio_sm_set_clkdiv_int_frac(pio, BB_AUDIO_SM, (uint16_t)(div256 >> 8), (uint8_t)(div256 & 0xFFu));
    const int ch = dma_claim_unused_channel(false);
    if (ch < 0) { bb_au_n[0] = 3u; return; }
    dma_channel_config c = dma_channel_get_default_config((uint)ch);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, true);
    channel_config_set_write_increment(&c, false);
    channel_config_set_ring(&c, false, BB_AU_RING_BITS);
    channel_config_set_dreq(&c, pio_get_dreq(pio, BB_AUDIO_SM, true));
    dma_channel_configure((uint)ch, &c, &pio->txf[BB_AUDIO_SM], (const void *)bb_au_ring,
                          dma_encode_endless_transfer_count(), true);
    bb_au_w = BB_AU_LEAD;                             /* start with half a ring of silence */
    bb_au_tone_left = BB_AUDIO_RATE;                  /* BB_AUDIO_V2: then a 1 s test tone */
    bb_au_dma = ch;
    pio_sm_set_enabled(pio, BB_AUDIO_SM, true);
    bb_au_n[0] = 1u;
}
#define BB_AU_SERVICE() do { if (bb_au_need()) bb_au_pump(); } while (0)
/* for core 0's report line */
void bb_audio_diag(unsigned long out[9])
{
    for (unsigned i = 0; i < 9u; ++i) out[i] = bb_au_n[i];
    bb_au_n[7] = 0; bb_au_n[8] = 0;                   /* level meters restart each report */
}
#else
#define BB_AU_SERVICE() ((void)0)
void bb_audio_diag(unsigned long out[9]) { for (unsigned i = 0; i < 9u; ++i) out[i] = 0u; }
#endif
#if BB_CORE1_SRAM_WAIT
#include "hardware/dma.h"
#include "hardware/timer.h"
/* Wait until the LCD strip's DMA has finished and the SPI has drained - the two
 * loops mr_pico_ili9341_flush_wait() runs - so that call then falls through. */
static void __noinline __not_in_flash_func(bb_c1_lcd_settle)(void) {
    if (!lcd.dma_active) return;
    while (dma_hw->ch[lcd.dma_chan].al1_ctrl & DMA_CH0_CTRL_TRIG_BUSY_BITS) { BB_AU_SERVICE(); }
    while (spi_get_hw(lcd.spi)->sr & SPI_SSPSR_BSY_BITS) { BB_AU_SERVICE(); }
}
static void __noinline __not_in_flash_func(bb_c1_wait_us)(uint32_t us) {
    const uint32_t t0 = timer_hw->timerawl;
    while ((uint32_t)(timer_hw->timerawl - t0) < us) { BB_AU_SERVICE(); }
}
#define BB_C1_WAIT_US(us) bb_c1_wait_us(us)
#define BB_C1_LCD_SETTLE() bb_c1_lcd_settle()
#else
#define BB_C1_WAIT_US(us) sleep_us(us)
#define BB_C1_LCD_SETTLE() ((void)0)
#endif

static void bb_v27_presenter(void) {
#if BB_AUDIO
    bb_au_start();                                   /* BB_AUDIO_V1: on core 1 */
#endif
    for (;;) {
        if (!__atomic_load_n(&bb_v27_request,__ATOMIC_ACQUIRE)) {
            __atomic_store_n(&bb_v27_parked,1u,__ATOMIC_RELEASE);
            BB_C1_WAIT_US(1000u);
            continue;
        }
        __atomic_store_n(&bb_v27_parked,0u,__ATOMIC_RELEASE);
        __atomic_store_n(&bb_v27_busy,1u,__ATOMIC_RELEASE);
        if (!__atomic_load_n(&bb_v27_request,__ATOMIC_ACQUIRE)) {
            __atomic_store_n(&bb_v27_busy,0u,__ATOMIC_RELEASE);
            continue;
        }
        __atomic_store_n(&bb_v29_stage,1u,__ATOMIC_RELAXED);
        __atomic_store_n(&bb_v29_heartbeat_us,time_us_32(),__ATOMIC_RELAXED);
        const uint32_t frame_start=time_us_32();
        uint32_t convert_total=0u, dma_total=0u;
        unsigned current=0u;
        const unsigned field_parity=bb_v32_field_parity;
        bb_v93_hash=2166136261u;
        uint32_t t=time_us_32();
        bb_v27_convert(BB_V32_DEST_Y(0u,field_parity),bb_v27_tiles[current]);
        convert_total+=(uint32_t)(time_us_32()-t);
        __atomic_store_n(&bb_v29_stage,2u,__ATOMIC_RELAXED);
        mr_pico_ili9341_flush_begin(NULL,0,(int)(10u+BB_V32_DEST_Y(0u,field_parity)),BB_V27_W,BB_V27_TILE_H,
                                     bb_v27_tiles[current],&lcd);
        for (unsigned i=1u;i<BB_V27_TILES;i++) {
            const unsigned next=current^1u;
            /* Convert next strip while SPI DMA transfers current strip. */
            t=time_us_32();
            bb_v27_convert(BB_V32_DEST_Y(i,field_parity),bb_v27_tiles[next]);
            BB_AU_SERVICE();                         /* BB_AUDIO_V1 */
            convert_total+=(uint32_t)(time_us_32()-t);
            t=time_us_32();
            __atomic_store_n(&bb_v29_stage,3u,__ATOMIC_RELAXED);
            BB_C1_LCD_SETTLE(); mr_pico_ili9341_flush_wait(NULL,&lcd);
            __atomic_store_n(&bb_v29_heartbeat_us,time_us_32(),__ATOMIC_RELAXED);
            dma_total+=(uint32_t)(time_us_32()-t);
            __atomic_add_fetch(&bb_v27_strips,1u,__ATOMIC_RELAXED);
            if (!__atomic_load_n(&bb_v27_request,__ATOMIC_ACQUIRE))
                goto stop_presenting;
            mr_pico_ili9341_flush_begin(NULL,0,(int)(10u+BB_V32_DEST_Y(i,field_parity)),
                                        BB_V27_W,BB_V27_TILE_H,
                                        bb_v27_tiles[next],&lcd);
            current=next;
        }
        t=time_us_32();
        BB_C1_LCD_SETTLE(); mr_pico_ili9341_flush_wait(NULL,&lcd);
        dma_total+=(uint32_t)(time_us_32()-t);
        __atomic_add_fetch(&bb_v27_strips,1u,__ATOMIC_RELAXED);
        const uint32_t frame_us=(uint32_t)(time_us_32()-frame_start);
        __atomic_add_fetch(&bb_v28_convert_us,convert_total,__ATOMIC_RELAXED);
        __atomic_add_fetch(&bb_v28_dma_us,dma_total,__ATOMIC_RELAXED);
        __atomic_add_fetch(&bb_v28_frame_us,frame_us,__ATOMIC_RELAXED);
        __atomic_store_n(&bb_v28_last_frame_us,frame_us,__ATOMIC_RELAXED);
        uint32_t max=__atomic_load_n(&bb_v28_max_frame_us,__ATOMIC_RELAXED);
        if(frame_us>max)__atomic_store_n(&bb_v28_max_frame_us,frame_us,__ATOMIC_RELAXED);
        __atomic_store_n(&bb_v29_stage,4u,__ATOMIC_RELAXED);
        __atomic_store_n(&bb_v29_heartbeat_us,time_us_32(),__ATOMIC_RELAXED);
        if (bb_v93_hash != bb_v93_last[field_parity&1u]) {      /* BB_V93_GAME_FPS */
            bb_v93_last[field_parity&1u]=bb_v93_hash;
            __atomic_add_fetch(&bb_v93_changed[field_parity&1u],1u,__ATOMIC_RELAXED);
        }
        __atomic_add_fetch(&bb_v27_frames,1u,__ATOMIC_RELAXED);
#if BB_LCD_LACE
        bb_v32_field_parity^=1u;
#endif
stop_presenting:
        /* On return to text mode, release LCD ownership before core 0
           redraws the DOS console.  Never leave DMA in flight. */
        BB_C1_LCD_SETTLE(); mr_pico_ili9341_flush_wait(NULL,&lcd);
        __atomic_store_n(&bb_v27_busy,0u,__ATOMIC_RELEASE);
#if BB_STAGE5D_VGA_MAX_FIELD_HZ != 0
        /* Both DMA buffers are free here. Core 0 can still park us on a
         * text-mode transition: poll request at most every 1 ms. Do not
         * use guest PIT time, sleep while SPI DMA is active, or alter VGA. */
        while (__atomic_load_n(&bb_v27_request,__ATOMIC_ACQUIRE)) {
            const uint32_t elapsed=(uint32_t)(time_us_32()-frame_start);
            const uint32_t period=1000000u / BB_STAGE5D_VGA_MAX_FIELD_HZ;
            if (elapsed>=period) break;
            const uint32_t remaining=period-elapsed;
            BB_C1_WAIT_US(remaining>1000u?1000u:remaining);
        }
#endif
    }
}

/* BB_AUDIO_V3: called by bb_live.c on every dispatch, in every video mode
 * (bb_lcd_vga_tick runs only once a program has set a video mode) */
void bb_audio_boot_tick(void)
{
#if BB_AUDIO
    if (!active || bb_v27_started) return;
    bb_au_prepare();
    printf("[bb-audio] core 1 audio: ring %p (cached %p) self-check=%lu (0=ok), I2S BCLK GP%u LRCLK GP%u DATA GP%u at %u Hz, 1 s test tone\n",
           (void *)bb_au_ring, (void *)bb_au_ring_cached, bb_au_n[6], (unsigned)BB_AUDIO_PIN_BCLK,
           (unsigned)(BB_AUDIO_PIN_BCLK + 1u), (unsigned)BB_AUDIO_PIN_DATA, (unsigned)BB_AUDIO_RATE);
    fflush(stdout);
    bb_v27_started = 1u;
    multicore_launch_core1(bb_v27_presenter);       /* parked until VGA; keeps audio flowing */
#endif
}
void bb_lcd_vga_tick(void) {
    if (!active) return;
#if BB_AUDIO
    if (!bb_v27_started) {      /* BB_AUDIO_V2: core 1 from the first tick, so text-mode programs have sound */
        bb_au_prepare();        /* core 0: the ring from the metadata pool */
        printf("[bb-audio] core 1 audio: ring %p (cached %p) self-check=%lu (0=ok), I2S BCLK GP%u LRCLK GP%u DATA GP%u at %u Hz, 1 s test tone\n",
               (void *)bb_au_ring, (void *)bb_au_ring_cached, bb_au_n[6], (unsigned)BB_AUDIO_PIN_BCLK,
               (unsigned)(BB_AUDIO_PIN_BCLK + 1u), (unsigned)BB_AUDIO_PIN_DATA, (unsigned)BB_AUDIO_RATE);
        fflush(stdout);
        bb_v27_started = 1u;
        multicore_launch_core1(bb_v27_presenter);   /* parked until VGA; keeps audio flowing */
    }
#endif
    if (bb_vga_active()) {
        /* v34: clear the physical margins left by the old 80x25 DOS HUD.
           Presenter only writes LCD rows 10..309.  On a mode transition,
           core 1 must be parked before core 0 touches LCD SPI/DMA. */
        if (!bb_v27_was_vga) {
            if (bb_v27_started) {
                __atomic_store_n(&bb_v27_request,0u,__ATOMIC_RELEASE);
                while (!__atomic_load_n(&bb_v27_parked,__ATOMIC_ACQUIRE))
                    tight_loop_contents();
            }
            mr_pico_ili9341_fill_screen(&lcd,0x0000u,480,320);
            bb_v32_field_parity=0u;
            puts("[bb-v34-lcd] VGA transition: full LCD cleared; viewport y=10..309; parity=0");
            fflush(stdout);
        }
        if (!bb_v27_started) {
            printf("[bb-v32-mode] %s rows=%u windows=%u bytes=%lu; fps_x10 counts %s\n",
#if BB_LCD_LACE
                "lace",(unsigned)(BB_V27_TILES*BB_V27_TILE_H), (unsigned)BB_V27_TILES,
                (unsigned long)(BB_V27_W*BB_V27_TILES*BB_V27_TILE_H*2u),"fields (two parity fields = one screen)"
#else
                "full",(unsigned)(BB_V27_TILES*BB_V27_TILE_H), (unsigned)BB_V27_TILES,
                (unsigned long)(BB_V27_W*BB_V27_TILES*BB_V27_TILE_H*2u),"complete frames"
#endif
            ); fflush(stdout);
            bb_v27_started=1u;
            multicore_launch_core1(bb_v27_presenter);
        }
        bb_v27_was_vga=1u;
        /* v38: Ctrl+P on the serial console parks core 1 (no PSRAM traffic)
           so XIP misses and MIPS can be compared with and without it. */
        __atomic_store_n(&bb_v27_request,bb_lcd_paused?0u:1u,__ATOMIC_RELEASE);
        /* Cheap dispatch counter: only inspect time and counters occasionally. */
        if ((++bb_v28_poll & 8191u)==0u) {
            const uint32_t ms=to_ms_since_boot(get_absolute_time());
            if (!bb_v28_report_ms) bb_v28_report_ms=ms;
            if ((uint32_t)(ms-bb_v28_report_ms)>=1000u) {
                const uint32_t f=__atomic_load_n(&bb_v27_frames,__ATOMIC_RELAXED);
                const uint32_t st=__atomic_load_n(&bb_v27_strips,__ATOMIC_RELAXED);
                const uint32_t cv=__atomic_load_n(&bb_v28_convert_us,__ATOMIC_RELAXED);
                const uint32_t dm=__atomic_load_n(&bb_v28_dma_us,__ATOMIC_RELAXED);
                const uint32_t ft=__atomic_load_n(&bb_v28_frame_us,__ATOMIC_RELAXED);
                const uint32_t delta_ms=(uint32_t)(ms-bb_v28_report_ms);
                printf("[bb-v28-lcd] fps_x10=%lu frames=%lu strips=%lu convert-ms=%lu dma-wait-ms=%lu frame-ms=%lu last-frame-us=%lu max-frame-us=%lu spi-hz=%lu\n",
                    (unsigned long)(((f-bb_v28_report_frames)*10000u)/delta_ms),
                    (unsigned long)(f-bb_v28_report_frames),
                    (unsigned long)(st-bb_v28_report_strips),
                    (unsigned long)((cv-bb_v28_report_convert)/1000u),
                    (unsigned long)((dm-bb_v28_report_dma)/1000u),
                    (unsigned long)((ft-bb_v28_report_frame)/1000u),
                    (unsigned long)__atomic_load_n(&bb_v28_last_frame_us,__ATOMIC_RELAXED),
                    (unsigned long)__atomic_load_n(&bb_v28_max_frame_us,__ATOMIC_RELAXED),
                    (unsigned long)lcd.spi_baud_hz);
                printf("[bb-v29-health] stage=%lu heartbeat-age-ms=%lu clk-peri=%lu spi-actual=%lu dma-active=%lu\n",
                   (unsigned long)__atomic_load_n(&bb_v29_stage,__ATOMIC_RELAXED),
                   (unsigned long)((uint32_t)(time_us_32()-__atomic_load_n(&bb_v29_heartbeat_us,__ATOMIC_RELAXED))/1000u),
                   (unsigned long)clock_get_hz(clk_peri),
                   (unsigned long)spi_get_baudrate(lcd.spi),
                   (unsigned long)lcd.dma_active);
                {   const uint32_t c0=__atomic_load_n(&bb_v93_changed[0],__ATOMIC_RELAXED);   /* BB_V93_GAME_FPS */
                    const uint32_t c1=__atomic_load_n(&bb_v93_changed[1],__ATOMIC_RELAXED);
                    const uint32_t d0=c0-bb_v93_report_changed[0], d1=c1-bb_v93_report_changed[1];
#if BB_LCD_LACE
                    const uint32_t div=2u;
#else
                    const uint32_t div=1u;
#endif
                    printf("[bb-v93-game] fps_x10=%lu changed-fields=%lu/%lu (game frames/s: new guest screens; exact below %lu/s)\n",
                           (unsigned long)(((d0>d1?d0:d1)*10000u)/delta_ms),
                           (unsigned long)d0,(unsigned long)d1,
                           (unsigned long)(((f-bb_v28_report_frames)*1000u)/delta_ms/div));
                    bb_v93_report_changed[0]=c0; bb_v93_report_changed[1]=c1; }
                bb_v28_report_ms=ms; bb_v28_report_frames=f;
                bb_v28_report_strips=st; bb_v28_report_convert=cv;
                bb_v28_report_dma=dm; bb_v28_report_frame=ft;
            }
        }
        return;
    }
    __atomic_store_n(&bb_v27_request,0u,__ATOMIC_RELEASE);
    if (bb_v27_was_vga) {
        /* Rare mode transition: wait only for the in-flight DMA transfer,
           not a full screen. This path never executes during VGA. */
        while (!__atomic_load_n(&bb_v27_parked,__ATOMIC_ACQUIRE))
            tight_loop_contents();
        bb_v27_was_vga=0u;
        memset(dirty,1,sizeof dirty);
        next_status_ms=0;
        bb_lcd_console_flush();
    }
}
