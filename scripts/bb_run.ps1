[CmdletBinding()]
param(
 [string]$MicroDos='C:\microDOS',
 [string]$Port='COM5',
 [int]$Seconds=120,
 [switch]$BuildOnly,
 [switch]$NoBuild,
 [switch]$NoFlash,
 [switch]$NoInput,
 [switch]$AutoDos2Test
)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logs=Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$log=Join-Path $logs "bb-$stamp-console.txt"
$report=Join-Path $logs "bb-$stamp-report.json"
$uf2=Join-Path $MicroDos 'build-pico\out\microdos_pico.uf2'
$picotool=Join-Path $HOME '.pico-sdk\picotool\2.3.0\picotool\picotool.exe'
$serial=$null
$state=[ordered]@{name='blitzBUS';timestamp=$stamp;target='microdos_pico';port=$Port;build='SKIPPED';flash='SKIPPED';cdc='NOT_OPENED';boot='NOT_OBSERVED';dos2test='NOT_RUN';lcd='NOT_HARDWARE_VERIFIED';audio='NOT_INTEGRATED';cpu_engine='microDOS AOT/interpreter';blitz86_dos_active=$false;transcript=$log;result='INCOMPLETE';error=''}
function Save-Report { $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $report -Encoding UTF8 }
function Checked([string]$label,[scriptblock]$task){
 Write-Host "=== $label ==="
 & $task
 if($LASTEXITCODE -ne 0){throw "$label exit code $LASTEXITCODE"}
}
try {
 if(-not $NoBuild){
   $mdBat=Join-Path $MicroDos 'md.bat'
   if(!(Test-Path $mdBat)){throw "Missing $mdBat"}
   Push-Location $MicroDos
   try {
      Checked 'microDOS host tools, disk and Pico build' { & $mdBat build pico }
      Checked 'blitzBUS firmware' { & cmake --build (Join-Path $MicroDos 'build-pico\out') --target microdos_pico }
   } finally {Pop-Location}
   $state.build='PASS'
 }
 if(!(Test-Path $uf2)){throw "Firmware missing: $uf2"}
 if($BuildOnly){$state.result='BUILD_COMPLETE';Save-Report;Write-Host "REPORT: $report";exit 0}
 if(-not $NoFlash){
  if(!(Test-Path $picotool)){throw "picotool missing: $picotool"}
  $ok=$false
  for($attempt=1;$attempt -le 3 -and -not $ok;$attempt++){
    Write-Host "=== Pico flash attempt $attempt/3 ==="
    try {& $picotool reboot -f -u 2>&1 | Out-Host}catch{Write-Host "BOOTSEL reboot transient: $_"}
    Start-Sleep -Milliseconds 1200
    & $picotool load -v -x $uf2 2>&1 | Out-Host
    $ok=($LASTEXITCODE -eq 0)
    if(-not $ok){Start-Sleep -Milliseconds 1300}
  }
  if(-not $ok){throw 'Pico flash failed after three attempts'}
  $state.flash='PASS'
 }
 Write-Host "=== Find application CDC: $Port ==="
 $deadline=(Get-Date).AddSeconds(30)
 do {
   $found=Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue | Where-Object {
      $_.DeviceID -eq $Port -and $_.PNPDeviceID -match 'VID_2E8A' -and $_.PNPDeviceID -match 'PID_0009|PID_000A'
   } | Select-Object -First 1
   if(-not $found){Start-Sleep -Milliseconds 200}
 } until($found -or (Get-Date) -gt $deadline)
 if(-not $found){throw "Application CDC not found on $Port"}
 $serial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
 $serial.DtrEnable=$true;$serial.ReadTimeout=100;$serial.Open()
 $state.cdc='PASS'
 Write-Host '=== Interactive COM console ==='
 Write-Host 'Type DOS commands here. Ctrl+] asks microDOS for its execution stats. Ctrl+X exits capture.'
 $text='';$launched=$false
 $until=(Get-Date).AddSeconds($Seconds)
 while((Get-Date) -lt $until){
    $chunk=$serial.ReadExisting()
    if($chunk){
        Write-Host -NoNewline $chunk
        [System.IO.File]::AppendAllText($log,$chunk)
        $text+=$chunk
        if($text.Length -gt 80000){$text=$text.Substring($text.Length-80000)}
        if($text -match 'microDOS for Pico 2|kernel:\s+MSDOS\.SYS'){$state.boot='BANNER_OBSERVED'}
        if($text -match '(?m)([A-Z]:\\|[A-Z]>|COMMAND\.COM)'){$state.boot='SHELL_OR_COMMAND_OBSERVED'}
        if($AutoDos2Test -and !$launched -and $text -match '([A-Z]:\\>|[A-Z]>)'){
          $serial.Write("DOS2TEST`r");$launched=$true;$state.dos2test='COMMAND_SENT'
          Write-Host "`n[blitzBUS] DOS2TEST sent through COM`n"
        }
        if($text -match '(?im)DOS2TEST[^\r\n]*(PASS|FAIL)'){$state.dos2test=$Matches[1].ToUpperInvariant()}
    }
    if(-not $NoInput){
      try {
        if([Console]::KeyAvailable){
            $k=[Console]::ReadKey($true)
            $ch=$k.KeyChar
            if([int][char]$ch -eq 24){break}
            if($k.Key -eq [ConsoleKey]::Enter){$serial.Write("`r");Write-Host ''}
            elseif([int][char]$ch -gt 0){$serial.Write([string]$ch);Write-Host -NoNewline $ch}
        }
      }catch{ if(-not $script:inputWarning){Write-Host 'Terminal has no interactive keyboard; use -NoInput or standard console host.';$script:inputWarning=$true} }
    }
    Start-Sleep -Milliseconds 15
 }
 if($state.boot -eq 'NOT_OBSERVED'){$state.result='CAPTURED_NO_BOOT_MARKER'}else{$state.result='BOOT_OBSERVED'}
} catch {$state.result='FAIL';$state.error=[string]$_;Write-Host "ERROR: $_";exit 1}
finally {
 if($null -ne $serial){if($serial.IsOpen){$serial.Close()};$serial.Dispose()}
 Save-Report
 Write-Host "`nCONSOLE: $log"
 Write-Host "REPORT:  $report"
 Write-Host "RESULT:  $($state.result)"
}
