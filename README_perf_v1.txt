BB_DOS622_PERF_V1 (extract over C:\blitzBUS, rebuild):
* DOS622_HDD.IMG: FatFs fast seek (cluster link map) instead of walking the
  FAT chain on every backward seek; f_sync every 64 sector writes instead of
  after each one (full aligned sectors are written to the card directly).
  Boot prints "[bb622-hdd] fast seek ON (...)" (or why it is off).
* SD SPI1 stays at 12.5 MHz (25 MHz failed reads on the test card);
  -DBB622_SD_SPI_HZ=... to experiment.
