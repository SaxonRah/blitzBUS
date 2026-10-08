[CmdletBinding()]
param(
    [string]$MicroDOS='C:\microDOS',
    [string]$Blitz86='C:\blitz86_v2',
    [string]$Port='COM5',
    [int]$Seconds=180,
    [switch]$NoBuild,
    [switch]$NoFlash,
    [switch]$NoInput,
    [switch]$AutoTests
)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$MicroDOS=(Resolve-Path -LiteralPath $MicroDOS).Path
$Blitz86=(Resolve-Path -LiteralPath $Blitz86).Path
$target='blitzbus_pico_b86_dos'
$firmware=Join-Path $MicroDOS "build-pico\out\$target.uf2"
$logs=Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$log=Join-Path $logs "bb-live-$stamp-console.txt"
$report=Join-Path $logs "bb-live-$stamp-report.json"
$state=[ordered]@{result='INCOMPLETE';target=$target;port=$Port;build='SKIPPED';flash='SKIPPED';cdc='NOT_OPENED';lcd='NOT_OBSERVED';dos2test='NOT_RUN';mdstress='NOT_RUN';backend='NOT_VERIFIED';retired=[uint64]0;blocks=[uint64]0;ready=$false;transcript=$log;error=''}
$serial=$null
$quit=$false
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
    $statsSentAt=$null
    $deadline=(Get-Date).AddSeconds($Seconds)
    while((Get-Date) -lt $deadline){
        $chunk=$serial.ReadExisting()
        if($chunk){
            Write-Host -NoNewline $chunk
            [System.IO.File]::AppendAllText($log,$chunk)
            $text += $chunk
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
                    $ch=$k.KeyChar
                    if([int][char]$ch -eq 24){$quit=$true;break}
                    if($k.Key -eq [ConsoleKey]::Enter){$serial.Write("`r");Write-Host ''}
                    elseif([int][char]$ch -gt 0){$serial.Write([string]$ch);Write-Host -NoNewline $ch}
                }
            } catch {
                if(!$inputWarning){Write-Host '[blitzBUS] Keyboard not available in this host. Use a standard PowerShell console.';$inputWarning=$true}
            }
        }
        if($AutoTests -and $statsSent -and $state.backend -eq 'blitz86-thumb2'){
            if($state.retired -gt 0 -and $state.blocks -gt 0 -and $state.ready){break}
            if(((Get-Date)-$statsSentAt).TotalSeconds -gt 5){break}
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
