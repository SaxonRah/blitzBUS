# BB_DOS622_COLOR_CELLS_V1 – color/CP437 screen renderer for the separate host runner.
# The raw serial stream is captured unchanged by bb_live_run_dos622_color.ps1.
$script:bbColorRows = New-Object 'string[]' 25
$script:bbColorAttrs = New-Object 'byte[][]' 25
$script:bbColorHasCells = New-Object 'bool[]' 25
$script:bbColorDirty = New-Object 'bool[]' 25
for ($i=0; $i -lt 25; $i++) {
    $script:bbColorRows[$i] = ''.PadRight(80)
    $script:bbColorAttrs[$i] = New-Object 'byte[]' 80
    for ($j=0; $j -lt 80; $j++) { $script:bbColorAttrs[$i][$j] = 7 }
    $script:bbColorDirty[$i] = $true
}
$script:bbColorPending = ''
$script:bbColorActive = $false
$script:bbColorFallback = $false
$script:bbColorLastDraw = [datetime]::MinValue
$script:bbColorLastScreenChange = [datetime]::UtcNow
$script:bbColorLastCpuCount = [decimal](-1)
$script:bbColorCpuProgress = 'unknown'
$script:bbColorLastEvent = ''
$script:bbColorAlert = ''
$script:bbColorOriginalFore = [ConsoleColor]::Gray
$script:bbColorOriginalBack = [ConsoleColor]::Black
$script:bbColorCp437 = [System.Text.Encoding]::GetEncoding(437)
$script:bbColorPalette = @(
    [ConsoleColor]::Black, [ConsoleColor]::DarkBlue, [ConsoleColor]::DarkGreen,
    [ConsoleColor]::DarkCyan, [ConsoleColor]::DarkRed, [ConsoleColor]::DarkMagenta,
    [ConsoleColor]::DarkYellow, [ConsoleColor]::Gray, [ConsoleColor]::DarkGray,
    [ConsoleColor]::Blue, [ConsoleColor]::Green, [ConsoleColor]::Cyan,
    [ConsoleColor]::Red, [ConsoleColor]::Magenta, [ConsoleColor]::Yellow,
    [ConsoleColor]::White
)

function Get-BbColorContrast {
    param([byte]$Attribute)
    $foreground = [int]($Attribute -band 15)
    $background = [int](($Attribute -shr 4) -band 7)
    # DOS dark foreground colors can be illegible in a host terminal.
    # Promote dim colors to the bright 8..15 palette, preserving hue.
    # Preserve black on bright backgrounds; expose black-on-black as white.
    if ($foreground -eq $background) {
        if ($background -eq 0) { $foreground = 15 } else { $foreground = if ($background -lt 4) { 15 } else { 0 } }
    } elseif ($foreground -gt 0 -and $foreground -lt 8 -and $background -eq 0) {
        $foreground = $foreground + 8
    }
    return @($foreground,$background)
}

function Set-BbColorLine {
    param([int]$Row,[string]$Text)
    if ($Row -lt 0 -or $Row -ge 25 -or $script:bbColorHasCells[$Row]) { return }
    if ($Text.Length -gt 80) { $Text=$Text.Substring(0,80) }
    $Text=$Text.PadRight(80)
    if ($script:bbColorRows[$Row] -cne $Text) {
        $script:bbColorRows[$Row] = $Text
        $script:bbColorDirty[$Row] = $true
        $script:bbColorLastScreenChange = [datetime]::UtcNow
    }
}

function Set-BbColorCells {
    param([int]$Row,[string]$Hex)
    if ($Row -lt 0 -or $Row -ge 25 -or $Hex.Length -ne 320) { return }
    if ($Hex -notmatch '^[0-9A-Fa-f]{320}$') { return }
    $chars = New-Object 'byte[]' 80
    $atts = New-Object 'byte[]' 80
    for ($i=0; $i -lt 80; $i++) {
        $chars[$i] = [Convert]::ToByte($Hex.Substring($i*4,2),16)
        if ($chars[$i] -lt 32) { $chars[$i] = 32 }
        $atts[$i] = [Convert]::ToByte($Hex.Substring($i*4+2,2),16)
    }
    $render = $script:bbColorCp437.GetString($chars)
    $changed = !$script:bbColorHasCells[$Row] -or $render -cne $script:bbColorRows[$Row]
    if (!$changed) {
        for ($i=0; $i -lt 80; $i++) {
            if ($script:bbColorAttrs[$Row][$i] -ne $atts[$i]) { $changed=$true; break }
        }
    }
    $script:bbColorHasCells[$Row]=$true
    if ($changed) {
        $script:bbColorRows[$Row]=$render
        $script:bbColorAttrs[$Row]=$atts
        $script:bbColorDirty[$Row]=$true
        $script:bbColorLastScreenChange=[datetime]::UtcNow
    }
}

function Write-BbDos622ColorEvent {
    param([string]$Line,[string]$View)
    # BB_DOS622_SWAP_LCD_V2: report disk swaps even in the static screen view.
    if ($Line -match '^\[bb622-swap\]') {
        $script:bbColorSwapAck=$Line
        try { [Console]::Title=($Line+' | Enter in DOS after OK') } catch {}
        $script:bbColorLastScreenChange=[datetime]::UtcNow
        if ($View -eq 'Events') { Write-Host $Line -ForegroundColor Cyan }
        return
    }
    if ($Line -match '^\[bb622-watch\].*?insns=(\d+)') {
        $count=[decimal]::Parse($Matches[1])
        if ($script:bbColorLastCpuCount -ge 0) {
            $script:bbColorCpuProgress = if ($count -gt $script:bbColorLastCpuCount) { 'CPU executing' } else { 'CPU count unchanged' }
        }
        $script:bbColorLastCpuCount=$count
    }
    if ($Line -match '^\[bb622-missing-bios\]|^\[bb622-hddv2\] FAIL|^\[bb622-hdd\] (READ|WRITE) FAIL|^\[bb-sd-b\] READ ERROR|^\[microDOS\] guest stopped|^\[blitzBUS\] FAIL') {
        $script:bbColorAlert=$Line
        if ($View -eq 'Events') { Write-Host $Line -ForegroundColor Yellow }
        if ($View -eq 'Screen') {
            try { [Console]::Title='blitzBUS DOS 6.22 | EMU ALERT: '+$Line.Substring(0,[Math]::Min(100,$Line.Length)) } catch {}
            # Keep screen intact; print one alert only after console exits.
        }
    } elseif ($View -eq 'Events' -and $Line -match '^\[bb622-floppyb\]|^\[bb622-ega\]|^\[bb622-hdd\] BIOS|^\[bb622-keyb\]|^\[bb622-vga') {
        Write-Host $Line
    }
}

function Show-BbDos622ColorFrame {
    if ($script:bbColorFallback) { return }
    $now=[datetime]::UtcNow
    $screenAge=[int]($now-$script:bbColorLastScreenChange).TotalSeconds
    try {
        if ($script:bbDesStage -ne 0) {
            [Console]::Title="Alt+G floppy $($script:bbDesDrive):$($script:bbDesDigit) | disk 0 eject | Enter commits | Esc cancels"
        } elseif ($script:bb622SwapStage -eq 1) {
            [Console]::Title='blitzBUS F9 floppy swap | choose A (DOS 6.22) or B (Descent); Esc cancels'
        } elseif ($script:bb622SwapStage -eq 2) {
            [Console]::Title="blitzBUS F9 floppy swap | drive $($script:bb622SwapDrive) disk 1..9; Esc cancels"
        } elseif ($script:bbColorActive -and $screenAge -ge 5) {
            [Console]::Title="blitzBUS DOS 6.22 | screen unchanged ${screenAge}s | $script:bbColorCpuProgress | Ctrl+X exit"
        }
    } catch {}
    if (($now-$script:bbColorLastDraw).TotalMilliseconds -lt 85) { return }
    $dirty=$false
    for ($i=0;$i -lt 25;$i++) { if ($script:bbColorDirty[$i]) { $dirty=$true;break } }
    if (!$dirty) { return }
    $script:bbColorLastDraw=$now
    try {
        $width=[Console]::BufferWidth
        if ($width -lt 42) { throw 'Need terminal width at least 42 columns' }
        $drawWidth=[Math]::Min(80,$width-1)
        if (!$script:bbColorActive) {
            $script:bbColorOriginalFore=[Console]::ForegroundColor
            $script:bbColorOriginalBack=[Console]::BackgroundColor
            [Console]::Clear()
            $script:bbColorActive=$true
            [Console]::Title='blitzBUS DOS 6.22 | CP437 + VGA colors | Ctrl+X exit'
        }
        for ($row=0;$row -lt 25;$row++) {
            if (!$script:bbColorDirty[$row]) { continue }
            $script:bbColorDirty[$row]=$false
            [Console]::SetCursorPosition(0,$row)
            $line=$script:bbColorRows[$row]
            if ($line.Length -lt 80) { $line=$line.PadRight(80) }
            $col=0
            while ($col -lt $drawWidth) {
                $pair=Get-BbColorContrast $script:bbColorAttrs[$row][$col]
                $f=[int]$pair[0]; $b=[int]$pair[1]
                $start=$col; $col++
                while ($col -lt $drawWidth) {
                    $next=Get-BbColorContrast $script:bbColorAttrs[$row][$col]
                    if ([int]$next[0] -ne $f -or [int]$next[1] -ne $b) { break }
                    $col++
                }
                [Console]::ForegroundColor=$script:bbColorPalette[$f]
                [Console]::BackgroundColor=$script:bbColorPalette[$b]
                [Console]::Write($line.Substring($start,$col-$start))
            }
        }
        [Console]::ForegroundColor=$script:bbColorOriginalFore
        [Console]::BackgroundColor=$script:bbColorOriginalBack
    } catch {
        $script:bbColorFallback=$true
        try {
            [Console]::ForegroundColor=$script:bbColorOriginalFore
            [Console]::BackgroundColor=$script:bbColorOriginalBack
        } catch {}
        Write-Host "`n[bb622-color] Console drawing failed. Try Windows Terminal 80x25 or -ConsoleView Events. $_"
    }
}

function Write-BbDos622ColorConsoleChunk {
    param([string]$Chunk,[string]$View)
    if (!$Chunk) { return }
    $script:bbColorPending += $Chunk
    while ($true) {
        $pos=$script:bbColorPending.IndexOf("`n")
        if ($pos -lt 0) { break }
        $line=$script:bbColorPending.Substring(0,$pos).TrimEnd("`r")
        $script:bbColorPending=$script:bbColorPending.Substring($pos+1)
        $m=[regex]::Match($line,'^\[bb622-cells\] row=(\d\d) \|([0-9A-Fa-f]{320})\|$')
        if ($m.Success) {
            if ($View -eq 'Screen') { Set-BbColorCells ([int]$m.Groups[1].Value) $m.Groups[2].Value }
            continue
        }
        $m=[regex]::Match($line,'^\[bb622-screen\] row=(\d\d) (?:\(cleared\)|\|(.*)\|)$')
        if ($m.Success) {
            if ($View -eq 'Screen') { Set-BbColorLine ([int]$m.Groups[1].Value) $m.Groups[2].Value }
        } else { Write-BbDos622ColorEvent $line $View }
    }
    if ($script:bbColorPending.Length -gt 8192) {
        $script:bbColorPending=$script:bbColorPending.Substring($script:bbColorPending.Length-8192)
    }
    if ($View -eq 'Screen') { Show-BbDos622ColorFrame }
}
