#ifndef BB_VGA_H
#define BB_VGA_H
#include <stdint.h>
#include <stdbool.h>
void bb_vga_init(uint8_t *memory);
bool bb_vga_int10(uint16_t *ax, uint16_t *bx, uint16_t *cx, uint16_t *dx,
                  uint16_t *es, uint16_t *bp, uint16_t *flags);
bool bb_vga_port_in(uint16_t port,uint8_t *result,uint64_t now_us);
bool bb_vga_port_out(uint16_t port,uint8_t value,uint64_t now_us);
bool bb_vga_active(void);
const uint8_t *bb_vga_framebuffer(void);
const uint16_t *bb_vga_palette565(void);
uint32_t bb_vga_palette_generation(void);
#endif
