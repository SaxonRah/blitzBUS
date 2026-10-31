# blitzBUS DOS Dual Keyboard V2
# Mirror + local keyboard editing; events sent through a one-owner file queue.
# This process NEVER accesses COM5.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Log,
    [string]$InputDir,
    [int]$ParentPid=0,
    [ValidateRange(20,1000)][int]$PollMilliseconds=80,
    [switch]$Replay
)
$ErrorActionPreference='Stop'
$colorModule=Join-Path $PSScriptRoot 'bb622_descent_color_host.ps1'
if(!(Test-Path -LiteralPath $colorModule -PathType Leaf)) {
    throw "Missing original CP437 color renderer: $colorModule"
}
# This dot-source only loads the pre-existing host display functions.
. $colorModule
$logPath=[System.IO.Path]::GetFullPath($Log)
$position=[long]0
$buffer=New-Object 'byte[]' 65536
$decoder=[System.Text.Encoding]::UTF8
$parentExitedAt=$null
$started=[datetime]::UtcNow
try { [Console]::Title='blitzBUS DOS 6.22 | COLOR KEYBOARD | LINE mode | F2 LIVE | Ctrl+X exit' } catch {}

$script:bbInputMode='LINE'
$script:bbBuffer=''
$script:bbCaret=0
$script:bbSwapStage=''
$script:bbSequence=0L
$script:bbInputStatus='Enter submits buffered line | F2 live | F9 swap | Ctrl+X exits'
$script:bbInputNeedsDraw=$true
$script:bbInputIsEnabled=![string]::IsNullOrWhiteSpace($InputDir)
$script:bbInputWarned=$false
$script:bbLastQueued=0L
$script:bbLastAcked=0L
$script:bbQueueStarted=[datetime]::UtcNow
$script:bbLastAckMode=''
$script:bbAckStatus=''
if($script:bbInputIsEnabled -and !(Test-Path -LiteralPath $InputDir -PathType Container)) { throw "Keyboard event directory does not exist: $InputDir" }

# Reserve rows 0..24 for DOS VGA, row 25 as a divider, row 26 for the
# persistent editable input line, and row 27 for keyboard status. The
# existing renderer ONLY paints rows 0..24 and will not erase input.
try {
    if([Console]::BufferHeight -lt 30){ [Console]::BufferHeight=30 }
    if([Console]::WindowHeight -lt 29) {
        $w=[Math]::Min([Console]::WindowWidth,[Console]::LargestWindowWidth)
        $h=[Math]::Min(29,[Console]::LargestWindowHeight)
        if($h -gt [Console]::WindowHeight){[Console]::SetWindowSize($w,$h)}
    }
} catch {
    Write-Host '[bb-dual-v2] Window resize unavailable; enlarge terminal to at least 29 rows.'
}

function Send-BbV2Event([int]$Key,[int]$Modifiers,[int]$Code) {
    if(!$script:bbInputIsEnabled){return}
    if($Key -lt 0 -or $Key -gt 255 -or $Modifiers -lt 0 -or $Modifiers -gt 7 -or $Code -lt 0 -or $Code -gt 255){
        $script:bbInputStatus='Key outside supported byte range; not sent'
        $script:bbInputNeedsDraw=$true
        return
    }
    $script:bbSequence++
    $name=('k_{0:D12}' -f $script:bbSequence)
    $temp=Join-Path $InputDir ($name+'.tmp')
    $event=Join-Path $InputDir ($name+'.evt')
    [System.IO.File]::WriteAllText($temp,"$Key,$Modifiers,$Code",[System.Text.Encoding]::ASCII)
    [System.IO.File]::Move($temp,$event)
}
function Send-BbV2Key($k) {
    Send-BbV2Event ([int]$k.Key) ([int]$k.Modifiers) ([int][char]$k.KeyChar)
}
function Send-BbV2Line {
    foreach($ch in $script:bbBuffer.ToCharArray()) {
        # Printable command characters do not need a synthetic scan code;
        # the protected runner consumes KeyChar for normal ASCII events.
        Send-BbV2Event 0 0 ([int][char]$ch)
    }
    Send-BbV2Event ([int][System.ConsoleKey]::Enter) 0 13
    $script:bbLastQueued=$script:bbSequence
    $script:bbQueueStarted=[datetime]::UtcNow
    $script:bbInputStatus="QUEUED $($script:bbBuffer.Length) chars + Enter; awaiting COM5 owner ACK"
    $script:bbBuffer=''
    $script:bbCaret=0
    $script:bbInputNeedsDraw=$true
}
function Read-BbV2OwnerAck {
    if(!$script:bbInputIsEnabled){return}
    $errPath=Join-Path $InputDir 'owner_error.txt'
    if(Test-Path -LiteralPath $errPath -PathType Leaf){
        try {
            $reason=([System.IO.File]::ReadAllText($errPath)).Trim()
            if($reason){
                $script:bbInputStatus="COM5 FORWARD ERROR: $reason"
                $script:bbInputNeedsDraw=$true
            }
        }catch{}
        return
    }
    $ackPath=Join-Path $InputDir 'owner_ack.txt'
    if(Test-Path -LiteralPath $ackPath -PathType Leaf){
        try {
            $raw=([System.IO.File]::ReadAllText($ackPath,[System.Text.Encoding]::ASCII)).Trim()
            $match=[regex]::Match($raw,'^(\d{12}),(SERIAL|HANDOFF)$')
            if($match.Success){
                $sequence=[long]::Parse($match.Groups[1].Value)
                if($sequence -gt $script:bbLastAcked){
                    $script:bbLastAcked=$sequence
                    $script:bbLastAckMode=$match.Groups[2].Value
                    if($script:bbLastQueued -gt 0 -and $sequence -ge $script:bbLastQueued){
                        $script:bbInputStatus="FORWARDED to COM5 (through seq=$sequence); guest echo not yet verified"
                    }else{
                        $script:bbInputStatus="COM5 owner active (seq=$sequence, $script:bbLastAckMode)"
                    }
                    $script:bbInputNeedsDraw=$true
                }
            }
        }catch{}
    }
    if($script:bbLastQueued -gt $script:bbLastAcked -and
       ([datetime]::UtcNow-$script:bbQueueStarted).TotalSeconds -gt 5){
        $script:bbInputStatus="QUEUE STALLED: owner ACK=$($script:bbLastAcked) expected=$($script:bbLastQueued); check RAW logger"
        $script:bbInputNeedsDraw=$true
    }
}

function Draw-BbV2Input([switch]$Force) {
    if(!$Force -and !$script:bbInputNeedsDraw){ return }
    $script:bbInputNeedsDraw=$false
    try {
        if([Console]::BufferWidth -lt 45 -or [Console]::BufferHeight -lt 29){
            if(!$script:bbInputWarned){
                $script:bbInputWarned=$true
                Write-Host '[bb-dual-v2] Color input needs console buffer at least 45x29.'
            }
            return
        }
        $width=[Math]::Min(80,[Console]::BufferWidth-1)
        $prefix="INPUT [$($script:bbInputMode)]> "
        $available=[Math]::Max(8,$width-$prefix.Length)
        $scroll=[Math]::Max(0,$script:bbCaret-$available+1)
        $tail=$script:bbBuffer.Substring($scroll,[Math]::Min($available,$script:bbBuffer.Length-$scroll))
        $render=($prefix+$tail).PadRight($width)
        $fore=[Console]::ForegroundColor
        $back=[Console]::BackgroundColor
        [Console]::ForegroundColor=[ConsoleColor]::Black
        [Console]::BackgroundColor=[ConsoleColor]::Gray
        [Console]::SetCursorPosition(0,25)
        [Console]::Write(('-'*$width).Substring(0,$width))
        [Console]::SetCursorPosition(0,26)
        [Console]::Write($render)
        [Console]::ForegroundColor=[ConsoleColor]::Gray
        [Console]::BackgroundColor=[ConsoleColor]::Black
        [Console]::SetCursorPosition(0,27)
        [Console]::Write($script:bbInputStatus.PadRight($width).Substring(0,$width))
        [Console]::ForegroundColor=$fore
        [Console]::BackgroundColor=$back
        $x=[Math]::Min($width-1,$prefix.Length+$script:bbCaret-$scroll)
        [Console]::SetCursorPosition($x,26)
    } catch {
        if(!$script:bbInputWarned) {
            $script:bbInputWarned=$true
            Write-Host "[bb-dual-v2] Persistent input line unavailable: $_"
        }
    }
}
function Handle-BbV2Keyboard {
    if(!$script:bbInputIsEnabled){ return }
    try {
        $max=16
        while($max-- -gt 0 -and [Console]::KeyAvailable) {
            $k=[Console]::ReadKey($true)
            if($k.Key -eq [ConsoleKey]::F2 -and $script:bbSwapStage -eq '') {
                if($script:bbInputMode -eq 'LINE' -and $script:bbBuffer.Length -gt 0){
                    $script:bbInputStatus='Submit with Enter or clear with Esc before switching to LIVE'
                    $script:bbInputNeedsDraw=$true
                    continue
                }
                $script:bbInputMode=if($script:bbInputMode -eq 'LINE') {'LIVE'} else {'LINE'}
                $script:bbInputStatus="Mode $script:bbInputMode | Enter sends line (LINE), per-key (LIVE)"
                $script:bbInputNeedsDraw=$true
                continue
            }
            $specialModifier=($k.Modifiers -band ([ConsoleModifiers]::Control -bor [ConsoleModifiers]::Alt)) -ne 0
            $value=[int][char]$k.KeyChar
            if($script:bbSwapStage -ne ''){
                Send-BbV2Key $k
                if($script:bbSwapStage -eq 'F9-DRIVE') {
                    if($k.Key -eq [ConsoleKey]::Escape){$script:bbSwapStage=''}
                    elseif($k.KeyChar -match '^[aAbB]$'){$script:bbSwapStage='F9-DISK'}
                }elseif($script:bbSwapStage -eq 'F9-DISK'){$script:bbSwapStage=''}
                elseif($script:bbSwapStage -eq 'ALTG-DRIVE'){
                    if($k.Key -eq [ConsoleKey]::Escape){$script:bbSwapStage=''}
                    elseif($k.KeyChar -match '^[aAbB]$'){$script:bbSwapStage='ALTG-DIGIT'}
                    elseif($k.KeyChar -match '^[0-9]$'){$script:bbSwapStage='ALTG-ENTER'}
                }elseif($script:bbSwapStage -eq 'ALTG-DIGIT'){
                    if($k.Key -eq [ConsoleKey]::Escape){$script:bbSwapStage=''}
                    elseif($k.KeyChar -match '^[0-9]$'){$script:bbSwapStage='ALTG-ENTER'}
                }elseif($script:bbSwapStage -eq 'ALTG-ENTER' -and ($k.Key -eq [ConsoleKey]::Enter -or $k.Key -eq [ConsoleKey]::Escape)){$script:bbSwapStage=''}
                $script:bbInputStatus="Disk swap $($script:bbSwapStage); wait for firmware ACK"
                $script:bbInputNeedsDraw=$true
                continue
            }
            if($k.Key -eq [ConsoleKey]::F9){
                Send-BbV2Key $k; $script:bbSwapStage='F9-DRIVE'
                $script:bbInputStatus='F9 swap: select A or B, then disk 0..9'
                $script:bbInputNeedsDraw=$true
                continue
            }
            if($k.Key -eq [ConsoleKey]::G -and (($k.Modifiers -band [ConsoleModifiers]::Alt) -ne 0 -or ($k.Modifiers -band [ConsoleModifiers]::Control) -ne 0)) {
                Send-BbV2Key $k
                $script:bbSwapStage='ALTG-DRIVE'
                $script:bbInputStatus='Alt/Ctrl+G swap: A/B, optional disk digit, Enter'
                $script:bbInputNeedsDraw=$true
                continue
            }
            if($specialModifier -or ($k.Key -ge [ConsoleKey]::F1 -and $k.Key -le [ConsoleKey]::F12)) {
                Send-BbV2Key $k
                $script:bbInputStatus="Immediate control: $($k.Key)"
                $script:bbInputNeedsDraw=$true
                continue
            }
            if($script:bbInputMode -eq 'LIVE') {
                Send-BbV2Key $k
                $script:bbInputStatus='LIVE: keystroke sent immediately | F2 switches to LINE'
                $script:bbInputNeedsDraw=$true
                continue
            }
            # BB_V2_EMPTY_LINE_KEYS_V1: with nothing typed in LINE mode, editing
            # and navigation keys belong to the DOS program (installer menus:
            # Esc backs up, arrows move), so send them straight through.
            if($script:bbBuffer.Length -eq 0 -and ($k.Key -eq [ConsoleKey]::Escape -or
               $k.Key -eq [ConsoleKey]::UpArrow -or $k.Key -eq [ConsoleKey]::DownArrow -or
               $k.Key -eq [ConsoleKey]::LeftArrow -or $k.Key -eq [ConsoleKey]::RightArrow -or
               $k.Key -eq [ConsoleKey]::Home -or $k.Key -eq [ConsoleKey]::End -or
               $k.Key -eq [ConsoleKey]::PageUp -or $k.Key -eq [ConsoleKey]::PageDown -or
               $k.Key -eq [ConsoleKey]::Insert -or $k.Key -eq [ConsoleKey]::Delete -or
               $k.Key -eq [ConsoleKey]::Backspace -or $k.Key -eq [ConsoleKey]::Tab)) {
                Send-BbV2Key $k
                $script:bbInputStatus="Sent $($k.Key) to DOS (empty line) | F2 LIVE sends every key"
                $script:bbInputNeedsDraw=$true
                continue
            }
            switch($k.Key) {
                ([ConsoleKey]::Enter) { Send-BbV2Line; break }
                ([ConsoleKey]::Backspace) {
                    if($script:bbCaret -gt 0) {
                        $script:bbBuffer=$script:bbBuffer.Remove($script:bbCaret-1,1)
                        $script:bbCaret--
                    }
                    break
                }
                ([ConsoleKey]::Delete) {
                    if($script:bbCaret -lt $script:bbBuffer.Length){$script:bbBuffer=$script:bbBuffer.Remove($script:bbCaret,1)}
                    break
                }
                ([ConsoleKey]::LeftArrow) { if($script:bbCaret -gt 0){$script:bbCaret--}; break }
                ([ConsoleKey]::RightArrow) { if($script:bbCaret -lt $script:bbBuffer.Length){$script:bbCaret++}; break }
                ([ConsoleKey]::Home) { $script:bbCaret=0; break }
                ([ConsoleKey]::End) { $script:bbCaret=$script:bbBuffer.Length; break }
                ([ConsoleKey]::Escape) { $script:bbBuffer='';$script:bbCaret=0;break }
                default {
                    if($value -ge 32 -and $value -le 126) {
                        if($script:bbBuffer.Length -lt 120){
                            $script:bbBuffer=$script:bbBuffer.Insert($script:bbCaret,[string]$k.KeyChar)
                            $script:bbCaret++
                        } else {$script:bbInputStatus='DOS input line limit 120 characters'}
                    } elseif($k.Key -ne [ConsoleKey]::NoName) { Send-BbV2Key $k }
                }
            }
            $script:bbInputNeedsDraw=$true
        }
    } catch {
        $script:bbInputStatus="Keyboard input error: $_"
        $script:bbInputNeedsDraw=$true
    }
}


function Test-BbParentAlive([int]$Id) {
    if($Id -le 0) { return $true }
    return ($null -ne (Get-Process -Id $Id -ErrorAction SilentlyContinue))
}
# V2: this window is the input owner, not an exit-key-only mirror.

# The log may not exist yet: firmware startup can precede the first append.
# All bytes are read from the start, so no screen rows are lost if this window
# is launched after DOS has already rendered several frames.
while($true) {
    Handle-BbV2Keyboard
    Read-BbV2OwnerAck
    $changed=$false
    if(Test-Path -LiteralPath $logPath -PathType Leaf) {
        try {
            $file=[System.IO.File]::Open($logPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
            try {
                if($file.Length -lt $position) {
                    # New/truncated log: start over, rather than seeking past EOF.
                    $position=0
                }
                # Bound processing per iteration to keep Ctrl+X responsive.
                $budget=1048576
                while($file.Length -gt $position -and $budget -gt 0) {
                    [void]$file.Seek($position,[System.IO.SeekOrigin]::Begin)
                    $take=[int][Math]::Min([long]$buffer.Length,
                         [Math]::Min($file.Length-$position,[long]$budget))
                    $got=$file.Read($buffer,0,$take)
                    if($got -le 0) { break }
                    $position+=$got
                    $budget-=$got
                    $changed=$true
                    Write-BbDos622ColorConsoleChunk ($decoder.GetString($buffer,0,$got)) 'Screen'
                }
            } finally { $file.Dispose() }
        } catch [System.IO.IOException] {
            # A brief open/rename race is harmless; resume from last offset.
        }
    }
    if($changed){$script:bbInputNeedsDraw=$true}
    Draw-BbV2Input
    if($Replay) {
        # Once all existing data is consumed, return without waiting for COM5.
        if(!$changed) { break }
    }
    if($ParentPid -gt 0 -and !(Test-BbParentAlive $ParentPid)) {
        if($null -eq $parentExitedAt) { $parentExitedAt=[datetime]::UtcNow }
        if(([datetime]::UtcNow-$parentExitedAt).TotalSeconds -ge 3) { break }
    }
    if(!$changed -and $ParentPid -eq 0 -and
       !(Test-Path -LiteralPath $logPath -PathType Leaf) -and
       ([datetime]::UtcNow-$started).TotalSeconds -ge 20) {
        throw "No console capture appeared within 20 seconds: $logPath"
    }
    Start-Sleep -Milliseconds $PollMilliseconds
}
