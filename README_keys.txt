Extract over C:\blitzBUS; no rebuild needed (restart the bb.bat session).
* scripts/bb_dos_dual_launch_v2.py (BB_DUAL_V2_SWAP_ENTER_V1): the dual
  console forwarded Enter straight to COM5, so the Alt+G / Ctrl+G picker
  never got its confirming Enter (no "[bb622-altg] SENT" in the log) and DOS
  got the Enter instead. While the picker (or the F9 picker) is open, Enter
  now goes to the picker.
* scripts/bb622_color_keyboard_v2.ps1 (BB_V2_EMPTY_LINE_KEYS_V1): in LINE
  mode with nothing typed, Esc, arrows, Home/End, PgUp/PgDn, Ins/Del,
  Backspace and Tab go straight to DOS. F2 = LIVE mode (every key sent).
