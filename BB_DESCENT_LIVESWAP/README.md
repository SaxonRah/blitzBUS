# blitzBUS live B: disk change (from A: prompt)

The five Descent IMG files are placed on SD **once**. After that, `A>DISK 1`, `A>DISK 2` etc change B: **without rebooting**. `DISK.COM` is an ordinary 8086 COM program using emulator INT F6/AH=B0. B: remains read-only, A:/C: unchanged.

1. Power off Pico, put SD in Windows, copy the five original floppy files once:

```powershell
python .\BB_DESCENT_LIVESWAP\prepare_disks.py --source C:\blitzBUS\games --sd O:\BLITZBUS --select 1
```

2. Install firmware and place `DISK.COM` into `DRIVE_C.IMG` using existing FAT16 utility (Pico still off):

```powershell
python .\BB_DESCENT_LIVESWAP\install.py --root C:\blitzBUS
python .\BB_FAT16_TOOL\fat16tool.py import .\BB_DESCENT_LIVESWAP\DISK.COM DISK.COM
```

3. Eject SD, power Pico, rebuild/flash as usual. At DOS prompt, copy `DISK.COM` once to A:, then operate entirely from A:

```dos
A>COPY C:\DISK.COM A:\DISK.COM
A>DISK 1
A>B:
B>DIR
B>A:
A>DISK 2
A>B:
B>DIR
```

Expect `[bb-sd-b] LIVE SWITCH B: disk=2 OK`. Switching from within B: may confuse DOS's current directory, so return to A: first. No card removal or reboot is needed between disk switches.

**Important:** This firmware and COM program have not yet been hardware tested. Make backups of BOOT.IMG and DRIVE_C.IMG before first use. This command uses emulator-defined INT F6; do not expect DISK.COM to run correctly on an ordinary PC. DOS 2.00 might cache disk buffers even after a media-change response; verify that B: DIR reflects each switch before running installer. Use only read-only Descent floppy images.

Rollback: `python .\BB_DESCENT_LIVESWAP\install.py --root C:\blitzBUS --restore` then rebuild.
