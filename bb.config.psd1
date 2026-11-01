# blitzBUS settings: the one place for the configuration you build and run with.
#
# These are the values of the last known-good firmware (the BB_* block that
# scripts\install_live.py wrote into C:\microDOS\pico\CMakeLists.txt).
# A variable that is already set in the PowerShell window always wins, so a
# one-off experiment never needs an edit here:
#     $env:BB_PJ_HOT_KB = '128'; .\bb.bat boot
# '.\bb.bat config' prints every effective value and where it came from.
@{
    # --- where things are -------------------------------------------------
    BB_MICRODOS      = 'C:\microDOS'      # microDOS checkout (firmware build tree)
    BB_BLITZ86       = 'C:\blitz86_v2'    # blitz86 checkout (CPU core)
    BB_PORT          = 'COM5'             # Pico USB serial port
    BB_SD_BOOT       = '1'                # boot DOS 6.22 from the SD card images
    BB_SD_SPI_HZ     = '12500000'         # SD card SPI clock after LCD init. Exact rates with
                                          # clk_peri 150 MHz: 12500000 15000000 18750000 25000000
	BB_META_KB 		 = '896'
    BB_SD_MULTI      = '64'               # sectors per SD command for DOS disk reads (0 = one at a time)
    BB_SYS_KHZ       = '360000'           # system clock (scripts\install_live.py: 150000..400000)

    BB_PM16_ADAPTIVE = '0'
    BB_PM16_LINK     = '0'
	
    # --- emulated CPU and memory (read by scripts\install_live.py) --------
    BB_CPU           = '386'              # 8086 | 186 | 286 | 386
    BB_386_NATIVE_T1 = '1'                # native 386 tier 1 (requires BB_CPU=386)
    BB_PAGED         = '1'                # paged guest memory
    BB_GUEST_KB      = '4096'             # guest RAM
    BB_CODE_KB       = '128'              # real-mode JIT code cache
    BB_BBUF          = '0'                # block buffer in SRAM (0 = off)
    BB_PM_IRQ0       = '0'                # keep 0: continuous protected-mode IRQ0 delivery is unsafe
    BB_PM_KBD        = '1'                # protected-mode keyboard IRQ
    BB_PM_RAM        = '1'                # protected-mode hot paths in SRAM

    # --- protected-mode JIT (blitz86 PJ) ----------------------------------
    BB_PJ            = '1'
    BB_PJ_PSRAM      = '1'                # translated-code cache in PSRAM
    BB_PJ_CODE_KB    = '1024'             # PSRAM code cache size
    BB_PJ_HOT_KB     = '92'               # SRAM hot tier size

    # --- profiling --------------------------------------------------------
    BB_PC_PROFILE    = '1'                # PC sampler lines in the console log

    # --- LCD --------------------------------------------------------------
    BB_LCD_SPI_HZ    = '75000000'         # 24000000 | 40000000 | 75000000
    # BB_LCD_PERI_HZ   = '150000000'        # 48000000 | 150000000
	BB_LCD_PERI_HZ   = 'sys/3'
    BB_LCD_LACE      = '1'                # interlaced strips
}
