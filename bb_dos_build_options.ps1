# blitzBUS DOS 6.22 build profile — edit THESE variables, not install_live.py.
# This script ONLY sets environment variables in your current PowerShell.
# It does NOT build firmware, open COM5, flash Pico, or alter a disk image.
# For CURRENT FLASHED FIRMWARE, use the normal -NoBuild -NoFlash launch.

$env:BB_SD_BOOT       = '1'          # SD/DOS image overlay; KEEP 1 for DOS622
$env:BB_CPU           = '286'        # 8086 | 186 | 286 only (NO 386/486 yet)
$env:BB_PAGED         = '1'          # Paged guest memory

$env:BB_HOT_THRESHOLD = '32'         # Native code promotion threshold
$env:BB_EVICT_CHUNK   = '4096'       # Code cache eviction chunk
$env:BB_EVICT_ROOM    = '2048'       # Room to leave during eviction
$env:BB_BBUF          = '1'          # SRAM frame buffer
$env:BB_CODE_KB       = '232'        # JIT SRAM code-cache KiB

$env:BB_LCD_PERI_HZ   = '150000000'  # LCD peripheral clock
$env:BB_LCD_SPI_HZ    = '75000000'   # SPI rate
$env:BB_LCD_LACE      = '1'          # 1 alternating rows, 0 full rows

Write-Host '[blitzBUS] DOS build variables set for this PowerShell.'
Write-Host '[blitzBUS] Nothing built or flashed. Use -NoBuild -NoFlash for existing firmware.'
