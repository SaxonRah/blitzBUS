/* blitzBUS SD phase 1 — wiring reused from microconsole. */
#include <stddef.h>
#include "hardware/spi.h"
#include "hw_config.h"
#include "sd_card.h"
static spi_t bus = {
    .hw_inst=spi1, .miso_gpio=12, .mosi_gpio=15, .sck_gpio=14,
    .baud_rate=12500000, .spi_mode=0, .no_miso_gpio_pull_up=false,
    .set_drive_strength=false, .use_static_dma_channels=false,
};
static sd_spi_if_t iface={.spi=&bus, .ss_gpio=13,.set_drive_strength=false};
static sd_card_t card={.type=SD_IF_SPI,.spi_if_p=&iface,.use_card_detect=false};
size_t sd_get_num(void) { return 1u; }
sd_card_t *sd_get_by_num(size_t i) { return i==0u ? &card:NULL; }
