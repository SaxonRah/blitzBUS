# Analysis of SWD v2: 3DBENCH, 80 samples

## Sample summary

- **JIT code cache:** 24 samples
- **other SRAM:** 39 samples
- **XIP flash:** 17 samples

These are instantaneous halt-PC samples, **not** a calibrated CPU-time breakdown or instruction counts. Earlier flash wait-loop samples cluster near benchmark startup.

## Native JIT-cache hits

- sample 02: `0x2002A140`
- sample 17: `0x200323A0`
- sample 28: `0x2002A066`
- sample 34: `0x2002A05E`
- sample 36: `0x2002A12A`
- sample 41: `0x20030EA6`
- sample 44: `0x2003F35A`
- sample 49: `0x20039108`
- sample 50: `0x2003F9B6`
- sample 51: `0x2003A666`
- sample 53: `0x2003FFF6`
- sample 54: `0x20036E40`
- sample 55: `0x2003D3FC`
- sample 56: `0x20039D90`
- sample 60: `0x20034B2A`
- sample 61: `0x2003482A`
- sample 62: `0x2003ED74`
- sample 63: `0x2003AA56`
- sample 65: `0x2003ECCC`
- sample 70: `0x2002BCAC`
- sample 73: `0x2002A1B0`
- sample 75: `0x20039942`
- sample 76: `0x2002D01C`
- sample 78: `0x2003A3B4`

## Relevant observations

- JIT code-cache allocation: 0x2002A040..0x2006403F (`bb_code`, 237,568 bytes); sampled PCs genuinely entered this region.
- v2 captures just 64 bytes per sample, usually too short to show the full code block.
- Repeated PC `0x1001B740` was resolved by the user to `sleep_until` in Pico SDK, with `wfe` and a backwards branch; it is not x86 JIT code.
- Current JIT dump windows cannot inherently identify guest `CS:IP`; v49f is needed for guest-block mapping, or new exported generation metadata.
- A small number of hit counts cannot establish which generated instruction sequence is worth optimizing without larger blocks and source metadata.
