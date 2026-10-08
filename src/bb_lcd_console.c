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
static void draw_glyph(uint16_t *dst,unsigned pitch,unsigned xx,unsigned yy,unsigned char c,uint16_t fg,uint16_t bg){
    const uint8_t *g=gfx_font5x7[(c>=32 && c<=127 ? c: '?')-32];
    for(unsigned gy=0;gy<8;gy++) for(unsigned gx=0;gx<6;gx++)
        dst[(yy+gy)*pitch+xx+gx]=(gy<7 && gx<5 && (g[gx]&(1u<<gy)))?fg:bg;
}
static void draw_row(unsigned r){
    for(unsigned x=0;x<COLS;x++) draw_glyph(pixels,COLS*CW,x*CW,0,cells[r][x],0xFFFFu,0x0000u);
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
#if BB_LCD_PERI_HZ == 150000000u
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
    row=col=0;characters=paint_rows=batches=0;active=1;next_status_ms=0;
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
    if((int32_t)(ms-next_status_ms)>=0){status_update();next_status_ms=ms+1000u;}
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
static volatile uint32_t bb_v27_busy;
static volatile uint32_t bb_v27_parked;
static uint32_t bb_v27_started;
static uint8_t bb_v27_was_vga;
static volatile uint32_t bb_v27_frames;
static volatile uint32_t bb_v27_strips;
static unsigned bb_v32_field_parity;
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
        bb_v31_expand_row(fb+src_y*320u,pal,out);
        memcpy(out+BB_V27_W,out,BB_V27_W*sizeof(*out));
        bb_v31_expand_row(fb+(src_y+1u)*320u,pal,out+2u*BB_V27_W);
    }
}

#endif

static void bb_v27_presenter(void) {
    for (;;) {
        if (!__atomic_load_n(&bb_v27_request,__ATOMIC_ACQUIRE)) {
            __atomic_store_n(&bb_v27_parked,1u,__ATOMIC_RELEASE);
            sleep_us(1000u);
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
            convert_total+=(uint32_t)(time_us_32()-t);
            t=time_us_32();
            __atomic_store_n(&bb_v29_stage,3u,__ATOMIC_RELAXED);
            mr_pico_ili9341_flush_wait(NULL,&lcd);
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
        mr_pico_ili9341_flush_wait(NULL,&lcd);
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
        __atomic_add_fetch(&bb_v27_frames,1u,__ATOMIC_RELAXED);
#if BB_LCD_LACE
        bb_v32_field_parity^=1u;
#endif
stop_presenting:
        /* On return to text mode, release LCD ownership before core 0
           redraws the DOS console.  Never leave DMA in flight. */
        mr_pico_ili9341_flush_wait(NULL,&lcd);
        __atomic_store_n(&bb_v27_busy,0u,__ATOMIC_RELEASE);
    }
}

void bb_lcd_vga_tick(void) {
    if (!active) return;
    if (bb_vga_active()) {
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
        __atomic_store_n(&bb_v27_request,1u,__ATOMIC_RELEASE);
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
