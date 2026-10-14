# blitzBUS DOS 6.22 LCD text-mode display V1

## The two independent failures in the October 14 log

1. `[bb622-hdd] optional image not opened fr=4` means `DOS622_HDD.IMG` is **not on the SD card**. The image is already supplied inside `BLITZBUS_DOS622_HDD_PHASE1.zip`. Extract it and copy it to `BLITZBUS/DOS622_HDD.IMG` on the Pico's microSD card. The extracted file is **33,546,240 bytes**. Do not replace or rename legacy `DRIVE_C.IMG`.
2. The DOS guest is running and the serial log mirrors `B800:0000` text, but the existing LCD presenter's regular tick is primarily a VGA mode 13h graphics path. A successful `LCD init PASS` / `LCD clear PASS` is not evidence that DOS text was transferred to the glass.

This *independent* LCD V1 layer uses the already allocated 80x25 LCD console `cells` and `dirty` arrays. It samples the guest's B800 character bytes at most every 80ms during DOS6 text mode and flushes only changed character rows. There are **no new framebuffer allocations**. It does not fake any BIOS response, change the DOS image, change 386/286 instructions, or change the ROM font definition. ASCII text is visible; extended CP437 line-drawing graphics are not yet translated.

## Install the LCD source layer

Extract `bb_dos622_lcd_text_v1.py` beside your existing installers at `C:\blitzBUS`. This script imports your already installed `bb_dos622_atbios_v1.py`; do not overwrite or remove it. The HDD installer must already have been installed, as in your latest log.

```powershell
cd C:\blitzBUS
python .\bb_dos622_lcd_text_v1.py selftest
python .\bb_dos622_lcd_text_v1.py probe
```

**Only if `probe` reports PASS:**

```powershell
python .\bb_dos622_lcd_text_v1.py apply
python .\bb_dos622_lcd_text_v1.py verify
python .\bb_dos622_hdd_v1.py verify
```

The patch touches `src/bb_live.c`, `src/bb_lcd_console.c`, and current checksum metadata. All modified bytes are backed up and reversible. Do **not** force a failed `probe`, alter SHA state manually, or use git patches.

## Test with the microSD image present

Shut down the Pico, remove its microSD card, place `DOS622_HDD.IMG` in `BLITZBUS` alongside `DOS622.IMG` and `DOS622.TXT`, eject the SD cleanly, and reinsert. Keep `DOS622.TXT` containing `1` and do not alter `DRIVE_C.IMG` or `BOOT.IMG`. Then run the same standard 180-second `scripts\bb_live_run.ps1` with CPU 286, 232KiB JIT, and current LCD settings.

Expected early log:

```
[bb622-hdd] BIOS 80h mounted RW 65x16x63, 65520 sectors, partition LBA 63, FAT16
```

Expected LCD log on first changed text row:

```
[bb622-lcdtext] B800 text shown on LCD; updated-rows=N
```

Do not treat these logs as LCD/hard-disk success unless you see the corresponding physical screen and DOS Setup recognizes the disk.

If the LCD remains completely blank even after the new `[bb622-lcdtext]` log, do a *single diagnostic* run at safer clock rates: `BB_LCD_PERI_HZ=48000000`, `BB_LCD_SPI_HZ=24000000`, `BB_LCD_LACE=0`. The log's `LCD init PASS` means the library called SPI successfully; it does **not** prove wiring/panel output. If the slow-speed diagnostic restores the display, debug LCD signal integrity/clocking; otherwise inspect screen power/backlight, wiring, panel init, and display connection. This is distinct from the DOS BIOS disk failure.

## Rollback

```powershell
python .\bb_dos622_lcd_text_v1.py verify
python .\bb_dos622_lcd_text_v1.py restore
```

If the current files have changed after installation, `restore` refuses by design. `recover` is for known partial installations, not unrelated source changes.

## Test status

- LF and CRLF reversible source/manifest tests: PASS.
- C11 compiled mirror test including rate gating and actual B800 text extraction: PASS.
- Pico build and physical LCD: NOT VERIFIED. Report exact `probe` and build output if either fails.
- Note: the user's previous HDD phase log showed `bb_dos622_atbios_v1.py verify` failing on a dependency manifest checksum after the HDD layer. This LCD installer does not erase or rewrite backups to mask that issue. Verify the latest HDD and LCD layers first, preserve the older installer state folders, and address old-layer verification separately if necessary.
