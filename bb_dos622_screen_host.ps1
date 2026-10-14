# blitzBUS DOS 6.22 stable host-side 80x25 console (no firmware changes).
# Dot-sourced only by generated bb_live_run_dos622.ps1.  Raw serial output
# remains byte-for-byte in the original bb-live-*-console.txt transcript.
$script:bb622HostRows = New-Object 'string[]' 25
for ($i=0; $i -lt 25; ++$i) { $script:bb622HostRows[$i] = '' }
$script:bb622HostPending = ''
$script:bb622HostActive = $false
$script:bb622HostDirty = $false
$script:bb622HostLastDraw = [datetime]::MinValue
$script:bb622HostFallback = $false
$script:bb622HostLastEvent = ''
$script:bb622HostEventCount = 0

function Write-BbDos622HostEvent {
    param([string]$Line, [string]$View)
    if ($Line -match '^\[bb622-missing-bios\]|^\[bb622-hddv2\] FAIL|^\[bb622-hdd\] (READ|WRITE) FAIL|^\[bb-sd-b\] READ ERROR|^\[microDOS\] guest stopped|^\[blitzBUS\] FAIL') {
        $script:bb622HostLastEvent = $Line
        if ($View -eq 'Events') { Write-Host $Line }
        elseif ($View -eq 'Screen') {
            try { [Console]::Title = 'blitzBUS DOS 6.22 | ' + $Line.Substring(0,[Math]::Min(110,$Line.Length)) }
            catch { }
            # Failures deserve visible text after the framebuffer, too.
            Write-Host "`n[EMU ALERT] $Line" -ForegroundColor Yellow
        }
    } elseif ($View -eq 'Events' -and $Line -match '^\[bb622-floppyb\]|^\[bb622-vga|^\[bb622-hdd\] BIOS|^\[bb622-lcdclear\]|^\[bb622-keyb|^\[bb-dos622\] ENTER') {
        Write-Host $Line
    }
}

function Show-BbDos622HostFrame {
    # The DOS program owns text echo.  Never ask Console.ReadLine here.
    if (!$script:bb622HostDirty) { return }
    $now=[datetime]::UtcNow
    if ($script:bb622HostActive -and ($now-$script:bb622HostLastDraw).TotalMilliseconds -lt 90) { return }
    $script:bb622HostDirty=$false
    $script:bb622HostLastDraw=$now
    if ($script:bb622HostFallback) { return }
    try {
        if (!$script:bb622HostActive) {
            [Console]::Clear()
            $script:bb622HostActive=$true
            try { [Console]::Title='blitzBUS MS-DOS 6.22 80x25 | Ctrl+X exit | full raw log in logs/' } catch { }
        }
        $width=[Console]::BufferWidth
        if ($width -lt 42) { throw 'Console buffer narrower than 42 columns' }
        $drawWidth=[Math]::Min(80,$width-1)  # Never wrap at the right edge.
        for ($r=0; $r -lt 25; ++$r) {
            $line=$script:bb622HostRows[$r]
            if ($line.Length -gt $drawWidth) { $line=$line.Substring(0,$drawWidth) }
            [Console]::SetCursorPosition(0,$r)
            [Console]::Write($line.PadRight($drawWidth))
        }
        # No WriteLine() or cursor reposition beyond row 24: never scroll the DOS screen.
    } catch {
        $script:bb622HostFallback=$true
        Write-Host "[bb622-host] Console cursor positioning unavailable; DOS screen is still in raw log. $_"
    }
}

function Write-BbDos622ConsoleChunk {
    param([string]$Chunk,[string]$View)
    if (!$Chunk) { return }
    $script:bb622HostPending += $Chunk
    # USB CDC may split lines anywhere. Keep only the incomplete suffix.
    while ($true) {
        $pos=$script:bb622HostPending.IndexOf("`n")
        if ($pos -lt 0) { break }
        $line=$script:bb622HostPending.Substring(0,$pos).TrimEnd("`r")
        $script:bb622HostPending=$script:bb622HostPending.Substring($pos+1)
        $m=[regex]::Match($line,'^\[bb622-screen\] row=(\d\d) (?:\(cleared\)|\|(.*)\|)$')
        if ($m.Success) {
            if ($View -eq 'Screen') {
                $row=[int]::Parse($m.Groups[1].Value)
                if ($row -ge 0 -and $row -lt 25) {
                    $newText=if ($m.Groups[2].Success) { $m.Groups[2].Value } else { '' }
                    if ($script:bb622HostRows[$row] -cne $newText) {
                        $script:bb622HostRows[$row]=$newText
                        $script:bb622HostDirty=$true
                    }
                }
            }
        } else { Write-BbDos622HostEvent $line $View }
    }
    if ($script:bb622HostPending.Length -gt 8192) {
        $script:bb622HostPending=$script:bb622HostPending.Substring($script:bb622HostPending.Length-8192)
    }
    if ($View -eq 'Screen') { Show-BbDos622HostFrame }
}
