[CmdletBinding()]
param(
    [string]$MicroDOS='C:\microDOS',
    [string]$Blitz86='C:\blitz86_v2',
    [string]$Port='COM5',
    [int]$Seconds=0,
    [switch]$NoBuild,
    [switch]$NoFlash,
    [switch]$NoInput,
    [switch]$AutoTests,
    [switch]$PhaseProfile,
    [ValidateSet('Screen','Events','Raw')]
    [string]$ConsoleView='Screen'
)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$MicroDOS=(Resolve-Path -LiteralPath $MicroDOS).Path
$Blitz86=(Resolve-Path -LiteralPath $Blitz86).Path
$target='blitzbus_pico_b86_dos'
$firmware=Join-Path $MicroDOS "build-pico\out\$target.uf2"
$logs=Join-Path $root 'logs'
$bb622SwapRequest=Join-Path $logs 'bb622-swap.request'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$log=Join-Path $logs "bb-live-$stamp-console.txt"
# BB622_SWAP_ACK_V3: independent, acknowledged swap control plane.
# This host alone owns COM5; external helpers send requests via an atomic file.
$bb622StatusPath=Join-Path $logs 'bb622-swap.status.json'
$bb622SessionPath=Join-Path $logs 'bb622-swap.session.json'
$bb622SessionId=[Guid]::NewGuid().ToString('N')
$bb622SessionAt=[datetime]::UtcNow
$bb622LastHeartbeat=[datetime]::MinValue
$bb622CurrentId=''
$bb622CurrentDisk=''
$bb622CurrentState='IDLE'
$bb622CurrentSent=[datetime]::MinValue
$bb622RxLines=''
function Write-Bb622Json([string]$file,[object]$body) {
    $data=ConvertTo-Json -InputObject $body -Compress -Depth 4
    $temp=$file+'.tmp.'+[Guid]::NewGuid().ToString('N')
    try {
        [System.IO.File]::WriteAllText($temp,$data,[System.Text.Encoding]::UTF8)
        if ([System.IO.File]::Exists($file)) { [System.IO.File]::Delete($file) }
        [System.IO.File]::Move($temp,$file)
    } finally { if ([System.IO.File]::Exists($temp)) { [System.IO.File]::Delete($temp) } }
}
function Set-Bb622SwapState([string]$state,[string]$detail) {
    $script:bb622CurrentState=$state
    $obj=[ordered]@{session=$bb622SessionId;request=$bb622CurrentId;disk=$bb622CurrentDisk;state=$state;detail=$detail;updatedUtc=[datetime]::UtcNow.ToString('o');transcript=$log}
    Write-Bb622Json $bb622StatusPath $obj
    [System.IO.File]::AppendAllText($log,"[bb622-ackhost] $state disk=$bb622CurrentDisk req=$bb622CurrentId $detail`n")
    try { [Console]::Title="blitzBUS $($bb622CurrentDisk): $state | $detail" } catch {}
}
# An earlier console's unconsumed request must not silently reach a new run.
if ([System.IO.File]::Exists($bb622SwapRequest)) {
    [System.IO.File]::Delete($bb622SwapRequest)
    [System.IO.File]::AppendAllText($log,"[bb622-ackhost] STALE REQUEST DISCARDED on new session`n")
}

$report=Join-Path $logs "bb-live-$stamp-report.json"
$state=[ordered]@{result='INCOMPLETE';target=$target;port=$Port;build='SKIPPED';flash='SKIPPED';cdc='NOT_OPENED';lcd='NOT_OBSERVED';dos2test='NOT_RUN';mdstress='NOT_RUN';backend='NOT_VERIFIED';retired=[uint64]0;blocks=[uint64]0;ready=$false;transcript=$log;error=''}
# BB_DOS622_COLOR_CELLS_V1 : host display only; original raw CDC log is preserved.
if ($ConsoleView -ne 'Raw') { . (Join-Path $PSScriptRoot 'bb_dos622_swap_color_host.ps1') }
$serial=$null
$quit=$false
$bb622SwapStage=0
$bb622SwapDrive=""
$inputWarning=$false
try {
    $installer=Join-Path $PSScriptRoot 'install_live.py'
    if(!(Test-Path -LiteralPath $installer)){throw "Missing installer: $installer"}
    & python $installer --microdos $MicroDOS --blitz86 $Blitz86
    if($LASTEXITCODE -ne 0){throw 'Live target installation failed'}
    if(!$NoBuild){
        & cmake --build (Join-Path $MicroDOS 'build-pico\out') --target $target
        if($LASTEXITCODE -ne 0){throw 'Live target build failed'}
        $state.build='PASS'
    }
    if(!(Test-Path -LiteralPath $firmware -PathType Leaf)){throw "Firmware missing: $firmware"}
    if(!$NoFlash){
        $picotool=Join-Path $HOME '.pico-sdk\picotool\2.3.0\picotool\picotool.exe'
        if(!(Test-Path -LiteralPath $picotool)){throw "picotool missing: $picotool"}
        $flashed=$false
        for($attempt=1;$attempt -le 3 -and !$flashed;$attempt++){
            Write-Host "=== Pico flash attempt $attempt/3 ==="
            try {& $picotool reboot -f -u 2>&1 | Out-Host} catch {Write-Host "BOOTSEL transition: $_"}
            Start-Sleep -Milliseconds 1200
            & $picotool load -v -x $firmware 2>&1 | Out-Host
            $flashed=($LASTEXITCODE -eq 0)
            if(!$flashed){Start-Sleep -Milliseconds 1200}
        }
        if(!$flashed){throw 'Pico flashing failed'}
        $state.flash='PASS'
    }
    Write-Host "=== Find application CDC: $Port ==="
    $until=(Get-Date).AddSeconds(30)
    do {
        $found=Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue | Where-Object {
            $_.DeviceID -eq $Port -and $_.PNPDeviceID -match 'VID_2E8A' -and $_.PNPDeviceID -match 'PID_0009|PID_000A'
        } | Select-Object -First 1
        if(!$found){Start-Sleep -Milliseconds 200}
    } until($found -or (Get-Date) -ge $until)
    if(!$found){throw "Pico application CDC not found on $Port"}
    $serial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
    $serial.DtrEnable=$true
    $serial.RtsEnable=$false
    $serial.ReadTimeout=100
    $serial.Open()
    $state.cdc='PASS'
    Write-Host '=== Interactive blitzBUS DOS console ==='
    Write-Host 'Type DOS commands. Ctrl+] requests counters; Ctrl+X exits. -AutoTests runs DOS2TEST and MDSTRESS automatically.'
    $text='';$dateSent=$false;$timeSent=$false;$testSent=$false;$stressSent=$false;$statsSent=$false
    $all='';$phase=0;$phaseState='';$doneTarget=0;$deltaTarget=0;$phaseDoneAt=$null;$phases=@()
    $statsSentAt=$null
    $deadline=(Get-Date).AddSeconds($Seconds)
    while($Seconds -le 0 -or (Get-Date) -lt $deadline){
        $chunk=$serial.ReadExisting()
        if($chunk){
            if ($ConsoleView -eq 'Raw') { Write-Host -NoNewline $chunk }
            else { Write-BbDos622ColorConsoleChunk $chunk $ConsoleView }
            [System.IO.File]::AppendAllText($log,$chunk)
            # BB622_SWAP_ACK_V3: parse complete raw CDC lines, including split reads.
            $bb622RxLines += $chunk
            if ($bb622RxLines.Length -gt 12000) { $bb622RxLines=$bb622RxLines.Substring($bb622RxLines.Length-12000) }
            while ($true) {
                $bb622Nl=$bb622RxLines.IndexOf("`n")
                if ($bb622Nl -lt 0) { break }
                $bb622Line=$bb622RxLines.Substring(0,$bb622Nl).TrimEnd("`r")
                $bb622RxLines=$bb622RxLines.Substring($bb622Nl+1)
                $m=[regex]::Match($bb622Line,'^\[bb622-swap\] ([AB]):([1-9]) (OK|FAIL)\b')
                if ($m.Success -and $bb622CurrentId -and $bb622CurrentDisk -eq ($m.Groups[1].Value+$m.Groups[2].Value)) {
                    if ($bb622CurrentState -eq 'SENT' -or $bb622CurrentState -eq 'NO_ACK') {
                        $result=if ($m.Groups[3].Value -eq 'OK') { 'OK' } else { 'FAIL' }
                        Set-Bb622SwapState $result $bb622Line
                    }
                }
            }

            $text += $chunk
            if($PhaseProfile){$all += $chunk}
            if($text.Length -gt 120000){$text=$text.Substring($text.Length-120000)}
            if($text.Contains('[blitzBUS] LCD panel init PASS')){$state.lcd='PASS'}
            if(!$dateSent -and $text.Contains('Enter new date:')){
                $serial.Write("`r");$dateSent=$true
                Write-Host '[blitzBUS] DOS date: default accepted'
            }
            if(!$timeSent -and $text.Contains('Enter new time:')){
                $serial.Write("`r");$timeSent=$true
                Write-Host '[blitzBUS] DOS time: default accepted'
            }
            if($AutoTests -and !$testSent -and $text -match '(?m)[A-Z]>'){
                $serial.Write("DOS2TEST`r");$testSent=$true;$state.dos2test='SENT'
                Write-Host '[blitzBUS] DOS2TEST sent'
            }
            if($testSent -and !$stressSent -and $text -match 'passed:\s*25\s+failed:\s*0' -and $text.Contains('ALL TESTS PASSED')){
                $state.dos2test='PASS'
                $serial.Write("MDSTRESS`r");$stressSent=$true;$state.mdstress='SENT'
                Write-Host '[blitzBUS] MDSTRESS sent'
            }
            if($stressSent -and !$statsSent -and $text.Contains('deterministic checksum = 0xA298')){
                $state.mdstress='PASS'
                $serial.Write([string][char]0x1D)
                $statsSent=$true;$statsSentAt=Get-Date
                Write-Host '[blitzBUS] Ctrl+] requested blitz86 counters'
            }
            $matchesB=[regex]::Matches($text,'\[bb-live\] backend=blitz86-thumb2 retired=(\d+) blocks=(\d+) ready=(\d+)')
            if($matchesB.Count -gt 0){
                $m=$matchesB[$matchesB.Count-1]
                $state.retired=[uint64]$m.Groups[1].Value
                $state.blocks=[uint64]$m.Groups[2].Value
                $state.ready=($m.Groups[3].Value -eq '1')
                $state.backend='blitz86-thumb2'
            }
        }
        if(!$NoInput){
            try {
                if([Console]::KeyAvailable){
                    $k=[Console]::ReadKey($true)
                    # BB_DOS622_SWAP_LCD_V2: F9 -> drive A/B -> disk number.
                    # Never pass menu selection to the DOS keyboard.
                    if($k.Key -eq [ConsoleKey]::F9 -or $k.KeyChar -eq [char]7 -or ($k.Key -eq [ConsoleKey]::G -and (($k.Modifiers -band [ConsoleModifiers]::Control) -ne 0))){
                        $bb622SwapStage=1
                        [Console]::Title='blitzBUS floppy swap | F9: choose A or B (Esc cancels)'
                        continue
                    }
                    if($bb622SwapStage -eq 1){
                        if($k.Key -eq [ConsoleKey]::Escape){
                            $bb622SwapStage=0;[Console]::Title='blitzBUS DOS 6.22 | floppy selection canceled'
                        } elseif($k.KeyChar -eq 'a' -or $k.KeyChar -eq 'A' -or
                                 $k.KeyChar -eq 'b' -or $k.KeyChar -eq 'B'){
                            $bb622SwapDrive=([string]$k.KeyChar).ToUpperInvariant()
                            $bb622SwapStage=2
                            [Console]::Title="blitzBUS floppy swap | $($bb622SwapDrive): press disk number 1..9 (Esc cancels)"
                        }
                        continue
                    }
                    if($bb622SwapStage -eq 2){
                        if($k.Key -eq [ConsoleKey]::Escape){
                            [Console]::Title='blitzBUS DOS 6.22 | floppy selection canceled'
                        } elseif($k.KeyChar -ge '1' -and $k.KeyChar -le '9'){
                            $number=[string]$k.KeyChar
                            if($bb622SwapDrive -eq 'B' -and [int]$number -gt 5){
                                [Console]::Title='blitzBUS B: supports DESCENT1..5.IMG only; press F9 to retry'
                            }else{
                                $serial.Write(([string][char]0x1C)+$bb622SwapDrive+$number)
                                [Console]::Title="blitzBUS | sent $($bb622SwapDrive):$number; check ACK then press Enter in DOS"
                            }
                        }
                        $bb622SwapStage=0
                        continue
                    }
                    $ch=$k.KeyChar
                    if([int][char]$ch -eq 24){$quit=$true;break}
                    $bb622SpecialKey = switch ([string]$k.Key) {
                        'F1' {'OP'} 'F2' {'OQ'} 'F3' {'OR'} 'F4' {'OS'}
                        'F5' {'[15~'} 'F6' {'[17~'} 'F7' {'[18~'} 'F8' {'[19~'}
                        'F9' {'[20~'} 'F10' {'[21~'} 'F11' {'[23~'} 'F12' {'[24~'}
                        'UpArrow' {'[A'} 'DownArrow' {'[B'}
                        'RightArrow' {'[C'} 'LeftArrow' {'[D'}
                        'Home' {'[H'} 'End' {'[F'}
                        'Insert' {'[2~'} 'Delete' {'[3~'}
                        'PageUp' {'[5~'} 'PageDown' {'[6~'}
                        default {''}
                    }
                    if ($bb622SpecialKey) {
                        $serial.Write(([string][char]27) + $bb622SpecialKey)
                    } elseif($k.Key -eq [ConsoleKey]::Enter){
                        # DOS/COMMAND.COM provides its own CRLF echo.
                        $serial.Write("`r")
                    } elseif($k.Key -eq [ConsoleKey]::Backspace){
                        # Forward ASCII BS once; guest handles erasure visually.
                        $serial.Write([string][char]0x08)
                    } elseif([int][char]$ch -gt 0){
                        # Never echo locally: guest is the terminal's echo owner.
                        $serial.Write([string]$ch)
                    }
                }
            } catch {
                if(!$inputWarning){Write-Host '[blitzBUS] Keyboard not available in this host. Use a standard PowerShell console.';$inputWarning=$true}
            }
        }
        if($PhaseProfile -and $statsSent){
            # per-phase profile: MDSTRESS 1..9, Ctrl+] after each (delta counters)
            $doneNow=[regex]::Matches($all,'deterministic checksum = 0x[0-9A-Fa-f]{4}').Count
            $deltaM=[regex]::Matches($all,'\[bb-live-delta\][^\r\n]*\r?\n')
            if($phase -eq 0 -and $deltaM.Count -ge 1){
                $phase=1;$phaseState='run';$doneTarget=$doneNow+1;$deltaTarget=$deltaM.Count+1
                $serial.Write("MDSTRESS 1`r");Write-Host '[blitzBUS] phase profile: MDSTRESS 1'
            } elseif($phase -ge 1 -and $phase -le 9){
                if($phaseState -eq 'run' -and $doneNow -ge $doneTarget){$phaseState='settle';$phaseDoneAt=Get-Date}
                if($phaseState -eq 'settle' -and ((Get-Date)-$phaseDoneAt).TotalMilliseconds -gt 400){
                    $serial.Write([string][char]0x1D);$phaseState='stats'
                }
                if($phaseState -eq 'stats' -and $deltaM.Count -ge $deltaTarget){
                    $line=$deltaM[$deltaM.Count-1].Value
                    $row=[ordered]@{phase=$phase}
                    foreach($m in [regex]::Matches($line,'([a-z\-]+)=(\d+)')){$row[$m.Groups[1].Value]=[uint64]$m.Groups[2].Value}
                    $phases += [pscustomobject]$row
                    $phase++
                    if($phase -le 9){
                        $phaseState='run';$doneTarget=$doneNow+1;$deltaTarget=$deltaM.Count+1
                        $serial.Write("MDSTRESS $phase`r");Write-Host "[blitzBUS] phase profile: MDSTRESS $phase"
                    }
                }
            } elseif($phase -gt 9){break}
        } elseif($AutoTests -and $statsSent -and $state.backend -eq 'blitz86-thumb2'){
            if($state.retired -gt 0 -and $state.blocks -gt 0 -and $state.ready){break}
            if(((Get-Date)-$statsSentAt).TotalSeconds -gt 5){break}
        }
        if ($ConsoleView -eq 'Screen') { Show-BbDos622ColorFrame }
        # BB622_SWAP_ACK_V3 - validate + transmit an external request.
        if ([System.IO.File]::Exists($bb622SwapRequest)) {
            try {
                $raw=[System.IO.File]::ReadAllText($bb622SwapRequest).Trim().ToUpperInvariant()
                [System.IO.File]::Delete($bb622SwapRequest)
                $match=[regex]::Match($raw,'^([AB])([1-9])\|([A-F0-9]{32})$')
                if (!$match.Success) {
                    $bb622CurrentId='invalid';$bb622CurrentDisk=''
                    Set-Bb622SwapState 'REJECTED' 'Invalid request; expected A2|32-character request ID'
                } elseif ($bb622CurrentState -eq 'SENT') {
                    # Caller must not create a second request until current one resolves.
                    [System.IO.File]::AppendAllText($log,"[bb622-ackhost] BUSY rejected request $raw`n")
                } else {
                    $disk=$match.Groups[1].Value+$match.Groups[2].Value
                    $requestId=$match.Groups[3].Value
                    $bb622CurrentId=$requestId
                    $bb622CurrentDisk=$disk
                    if ($disk[0] -eq 'B' -and [int][string]$disk[1] -gt 5) {
                        Set-Bb622SwapState 'REJECTED' 'B: supports disks 1..5'
                    } else {
                        $bb622CurrentSent=[datetime]::UtcNow
                        $serial.Write(([string][char]0x1C)+[string]$disk[0]+[string]$disk[1])
                        Set-Bb622SwapState 'SENT' 'CDC bytes transmitted; awaiting firmware response'
                    }
                }
            } catch {
                [System.IO.File]::AppendAllText($log,"[bb622-ackhost] REQUEST ERROR $($_)`n")
                try { Set-Bb622SwapState 'HOST_ERROR' ([string]$_) } catch {}
            }
        }
        # BB622_SWAP_ACK_V3 heartbeat: external caller refuses stale/unstarted consoles.
        $bb622Now=[datetime]::UtcNow
        if (($bb622Now-$bb622LastHeartbeat).TotalMilliseconds -ge 700) {
            Write-Bb622Json $bb622SessionPath ([ordered]@{session=$bb622SessionId;pid=$PID;lastUtc=$bb622Now.ToString('o');startedUtc=$bb622SessionAt.ToString('o');transcript=$log;port=$Port})
            $bb622LastHeartbeat=$bb622Now
        }
        if ($bb622CurrentState -eq 'SENT' -and ($bb622Now-$bb622CurrentSent).TotalSeconds -gt 12) {
            Set-Bb622SwapState 'NO_ACK' 'Pico did not confirm swap within 12 seconds; do NOT press Enter'
        }
        Start-Sleep -Milliseconds 15
    }
    if($AutoTests){
        if($state.dos2test -ne 'PASS'){throw 'DOS2TEST did not pass'}
        if($state.mdstress -ne 'PASS'){throw 'MDSTRESS checksum not observed'}
        if($state.backend -ne 'blitz86-thumb2'){throw 'No [bb-live] counter line received; Ctrl+] telemetry requires investigation'}
        if(!$state.ready -or $state.retired -eq 0 -or $state.blocks -eq 0){throw 'blitz86 counters missing/zero or JIT not ready'}
        $state.result='PASS'
        Write-Host "[blitzBUS] LIVE DOS JIT PASS retired=$($state.retired) blocks=$($state.blocks)"
        if($PhaseProfile){
            $state.phases=$phases
            Write-Host '[blitzBUS] MDSTRESS per-phase profile (deltas):'
            $phases | Format-Table phase,retired,native,translate,blocks,'native-misses','translate-misses','rt-step','rt-cond','rt-flags','rt-light','rt-smc',traps -AutoSize | Out-String | Write-Host
            if($phases.Count -lt 9){Write-Host "[blitzBUS] WARNING: only $($phases.Count) phases profiled (raise -Seconds?)"}
        }
    } elseif($quit){$state.result='INTERACTIVE_EXIT'}
    else {$state.result='CAPTURE_COMPLETE'}
} catch {
    $state.result='FAIL';$state.error=[string]$_
    Write-Host "[blitzBUS] FAIL: $_"
} finally {
    if($null -ne $serial){if($serial.IsOpen){$serial.Close()};$serial.Dispose()}
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding UTF8
    Write-Host "`nCONSOLE: $log"
    Write-Host "REPORT:  $report"
    Write-Host "RESULT:  $($state.result)"
}
if($state.result -eq 'FAIL'){exit 1}
