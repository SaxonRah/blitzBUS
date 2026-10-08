/* blitzBUS 0.1: real MS-DOS console -> MicroRender ST7796 RGB565 LCD.
 * Serial console remains authoritative for both input and output.
 * 80 columns x 25 rows, glyphs 5x7 in 6x12 cells at y=10..309.
 */
#include "bb_lcd_console.h"
#include "mr_pico_ili9341.h"
#include "gfx_font5x7.h"
#include "pico/stdlib.h"
#include <string.h>
#include <stdio.h>
#define COLS 80
#define ROWS 25
#define CELL_W 6
#define CELL_H 12
#define TOP 10
/* Match the verified MicroConsole Pico LCD configuration.  An uninitialized
 * context leaves spi=NULL and all GPIO pins zero: spi_init(NULL, ...) faults. */
static mr_pico_ili9341_t lcd = {
    .spi = MR_LCD_SPI,
    .dma_chan = 0u,
    .pin_miso = MR_LCD_PIN_MISO,
    .pin_cs = MR_LCD_PIN_CS,
    .pin_sck = MR_LCD_PIN_SCK,
    .pin_mosi = MR_LCD_PIN_MOSI,
    .pin_rst = MR_LCD_PIN_RST,
    .pin_dc = MR_LCD_PIN_DC,
    .spi_baud_hz = MR_LCD_SPI_BAUD,
    .x_offset = 0,
    .y_offset = 0,
    .dma_active = 0u,
    .spi_format_bits = 0u,
    .dma_cfg16 = {0}
};
static uint8_t cells[ROWS][COLS];
static uint8_t dirty[ROWS];
static uint16_t scanline[CELL_W * COLS * CELL_H];
static unsigned row, col;
static int active;
static void paint(int r) {
    for (int y=0;y<CELL_H;++y) {
        uint16_t *dst=scanline + y*(COLS*CELL_W);
        for (int x=0;x<COLS;++x) {
            uint8_t c=cells[r][x];
            const uint8_t *glyph=gfx_font5x7[(c>=32 && c<128?c:63)-32];
            for(int xx=0;xx<CELL_W;++xx)
                dst[x*CELL_W+xx]=(xx<5 && y>=2 && y<9 && (glyph[xx] & (1u<<(y-2)))) ? 0xFFFFu : 0x0000u;
        }
    }
    mr_pico_ili9341_flush(NULL,0,TOP+r*CELL_H,COLS*CELL_W,CELL_H,scanline,&lcd);
}
void bb_lcd_console_init(void) {
    memset(cells,' ',sizeof(cells));
    memset(dirty,1,sizeof(dirty));
    puts("[blitzBUS] LCD SPI init begin");
    fflush(stdout);
    mr_pico_ili9341_init(&lcd);
    puts("[blitzBUS] LCD SPI init PASS");
    fflush(stdout);
    puts("[blitzBUS] LCD panel init begin");
    fflush(stdout);
    mr_pico_ili9341_panel_init(&lcd);
    puts("[blitzBUS] LCD panel init PASS");
    fflush(stdout);
    puts("[blitzBUS] LCD clear begin");
    fflush(stdout);
    mr_pico_ili9341_fill_screen(&lcd,0x0000u,480,320);
    puts("[blitzBUS] LCD clear PASS");
    fflush(stdout);
    active=1;
}
static void newline(void) {
    col=0;
    if(row+1<ROWS){++row;return;}
    memmove(cells[0],cells[1],(ROWS-1)*COLS);
    memset(cells[ROWS-1],' ',COLS);
    memset(dirty,1,sizeof(dirty));
}
void bb_lcd_console_write(const uint8_t *data,size_t size) {
    if(!active)return;
    for(size_t i=0;i<size;++i) {
        unsigned c=data[i];
        if(c=='\r'){col=0;continue;}
        if(c=='\n'){newline();continue;}
        if(c=='\b'){if(col>0)--col;cells[row][col]=' ';dirty[row]=1;continue;}
        if(c=='\t'){unsigned n=8-(col&7u);while(n--){cells[row][col]=' ';dirty[row]=1;if(++col>=COLS)newline();}continue;}
        if(c<32)continue;
        if(col>=COLS)newline();
        cells[row][col]=(uint8_t)(c<128?c:'?');dirty[row]=1;
        if(++col>=COLS)newline();
    }
}
void bb_lcd_console_flush(void) {
    if(!active)return;
    for(int r=0;r<ROWS;++r)if(dirty[r]){paint(r);dirty[r]=0;}
}
