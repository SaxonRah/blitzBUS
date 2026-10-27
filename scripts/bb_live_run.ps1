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
$bbPicToggleRequest=Join-Path $logs 'bb622-picprobe.request'
$bb622IrqTrialRequest=Join-Path $logs 'bb622-irqtrial.request'
$bb622SwapRequest=Join-Path $logs 'bb622-swap.request'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$log=Join-Path $logs "bb-live-$stamp-console.txt"
$report=Join-Path $logs "bb-live-$stamp-report.json"
$state=[ordered]@{result='INCOMPLETE';target=$target;port=$Port;build='SKIPPED';flash='SKIPPED';cdc='NOT_OPENED';lcd='NOT_OBSERVED';dos2test='NOT_RUN';mdstress='NOT_RUN';backend='NOT_VERIFIED';retired=[uint64]0;blocks=[uint64]0;ready=$false;transcript=$log;error=''}
# BB_DOS622_COLOR_CELLS_V1 : host display only; original raw CDC log is preserved.
if ($ConsoleView -ne 'Raw') { . (Join-Path $PSScriptRoot 'bb622_descent_color_host.ps1') }
$serial=$null
$quit=$false
$bb622SwapStage=0
$bb622SwapDrive=""
$bbDesStage=0
$bbDesDrive='B'
$bbDesDigit=''
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
                    # BB622_DESCENT_SWAP_V1: Alt+G / Ctrl+G compact picker.
                    # Defaults to B: for Descent, 0 ejects, Enter commits.
                    # A/B can optionally be typed before the disk number.
                    $bbDesAlt = ($k.Key -eq [ConsoleKey]::G -and
                        (($k.Modifiers -band [ConsoleModifiers]::Alt) -ne 0))
                    $bbDesCtrl = ([int][char]$k.KeyChar -eq 7)
                    if ($bbDesAlt -or $bbDesCtrl) {
                        $bbDesStage=1; $bbDesDrive='B'; $bbDesDigit=''
                        try { [Console]::Title='Alt+G floppy | B: disk 0..5 (0=eject), A/B drive, Enter confirms' } catch {}
                        continue
                    }
                    if ($bbDesStage -ne 0) {
                        if ($k.Key -eq [ConsoleKey]::Escape) {
                            $bbDesStage=0; $bbDesDigit=''
                            try { [Console]::Title='Floppy choice cancelled' } catch {}
                            continue
                        }
                        if ($k.KeyChar -eq 'a' -or $k.KeyChar -eq 'A' -or
                            $k.KeyChar -eq 'b' -or $k.KeyChar -eq 'B') {
                            $bbDesDrive=([string]$k.KeyChar).ToUpperInvariant();$bbDesDigit=''
                            try { [Console]::Title="Alt+G floppy | $($bbDesDrive): choose disk (0=eject), then Enter" } catch {}
                            continue
                        }
                        if ($k.KeyChar -ge '0' -and $k.KeyChar -le '9') {
                            $wanted=[int]([string]$k.KeyChar)
                            if ($bbDesDrive -eq 'B' -and $wanted -gt 5) {
                                $bbDesDigit=''
                                try { [Console]::Title='B: only disk 0 (eject) or disks 1..5; retry' } catch {}
                            } else {
                                $bbDesDigit=[string]$k.KeyChar
                                try { [Console]::Title="Alt+G floppy | $($bbDesDrive):$bbDesDigit ready; ENTER to apply (Esc cancels)" } catch {}
                            }
                            continue
                        }
                        if ($k.Key -eq [ConsoleKey]::Enter) {
                            if ($bbDesDigit -ne '') {
                                $bbDesCode=$bbDesDrive+$bbDesDigit
                                $serial.Write(([string][char]0x1C)+$bbDesCode)
                                [System.IO.File]::AppendAllText($log,"[bb622-altg] SENT $bbDesCode waiting for firmware response`n")
                                try { [Console]::Title="blitzBUS $bbDesCode sent | wait for [bb622-swap] OK before DOS Enter" } catch {}
                                $bbDesStage=0;$bbDesDigit=''
                            }
                            continue
                        }
                        # While selecting a disk, don't accidentally type into DOS.
                        continue
                    }
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
                        } elseif($k.KeyChar -ge '0' -and $k.KeyChar -le '9'){
                            $number=[string]$k.KeyChar # BB_DOS622_BOOT_EJECT_V1: disk 0 eject
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
        # BB622_SWAP_CONTROLS_V1 - out-of-band requests for consoles where F9 is reserved.
        # The runner exclusively owns COM5; callers never open the serial port.
        if ([System.IO.File]::Exists($bb622SwapRequest)) {
            try {
                $bb622Raw = [System.IO.File]::ReadAllText($bb622SwapRequest).Trim().ToUpperInvariant()
                [System.IO.File]::Delete($bb622SwapRequest)
                if ($bb622Raw -match '^[AB][0-9]$') {
                    $bb622DiskDrive = $bb622Raw.Substring(0,1)
                    $bb622DiskNum = $bb622Raw.Substring(1,1)
                    if ($bb622DiskDrive -eq 'B' -and [int]$bb622DiskNum -gt 5) {
                        [Console]::Title = 'blitzBUS disk request rejected: B supports disks 1..5'
                    } else {
                        $serial.Write(([string][char]0x1C)+$bb622DiskDrive+$bb622DiskNum)
                        [System.IO.File]::AppendAllText($log,"[bb622-hostswap] SENT $($bb622DiskDrive):$bb622DiskNum awaiting firmware ACK`n")
                        [Console]::Title="blitzBUS swap $($bb622DiskDrive):$bb622DiskNum submitted; wait for OK then press Enter"
                    }
                } else {
                    [Console]::Title='blitzBUS disk request invalid: expected A2 or B3'
                }
            } catch {
                [Console]::Title='blitzBUS disk request failed: '+[string]$_
            }
        }
        # BB622_PIC_HOST_CONTROL_V1: service independent PIC-probe toggle request.
        # Exactly one requester is allowed; firmware sends [bb622-picprobe] ACK.
        if ([System.IO.File]::Exists($bbPicToggleRequest)) {
            try {
                $bbPicText=[System.IO.File]::ReadAllText($bbPicToggleRequest).Trim().ToUpperInvariant()
                if ($bbPicText -eq 'Y') {
                    [System.IO.File]::Delete($bbPicToggleRequest)
                    $serial.Write([string][char]0x19)
                    [System.IO.File]::AppendAllText($log,"[bb622-piccontrol] SENT Ctrl+Y 0x19 awaiting firmware ACK`n")
                } else {
                    [System.IO.File]::Delete($bbPicToggleRequest)
                    [System.IO.File]::AppendAllText($log,"[bb622-piccontrol] REJECT invalid request`n")
                }
            } catch {
                [System.IO.File]::AppendAllText($log,"[bb622-piccontrol] ERROR $($_.Exception.Message)`n")
            }
        }
        # BB622_IRQ0_TRIAL_V1: one-shot request from second window.
        if ([System.IO.File]::Exists($bb622IrqTrialRequest)) {
            try {
                $bb622IrqText=[System.IO.File]::ReadAllText($bb622IrqTrialRequest).Trim()
                [System.IO.File]::Delete($bb622IrqTrialRequest)
                if ($bb622IrqText -ceq 'ARM') {
                    $serial.Write([string][char]0x15)
                    [System.IO.File]::AppendAllText($log,"[bb622-irqtrial-host] SENT Ctrl+U 0x15`n")
                } else {
                    [System.IO.File]::AppendAllText($log,"[bb622-irqtrial-host] REJECT request`n")
                }
            } catch {
                [System.IO.File]::AppendAllText($log,"[bb622-irqtrial-host] ERROR $($_.Exception.Message)`n")
            }
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
