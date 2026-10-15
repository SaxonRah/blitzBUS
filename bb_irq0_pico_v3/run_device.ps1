[CmdletBinding()]
param(
 [string]$Port='COM5',
 [int]$Seconds=90,
 [switch]$Flash
)
$ErrorActionPreference='Stop'
$here=(Resolve-Path -LiteralPath $PSScriptRoot).Path
$uf2=Join-Path $here 'build-pico-ninja\bb_irq0_pico_v3.uf2'
if(!$Flash){throw 'Refusing to replace running firmware without explicit -Flash. Build first; then rerun with -Flash.'}
if(!(Test-Path -LiteralPath $uf2 -PathType Leaf)){throw "Missing compiled V3 UF2: $uf2"}
$picotool=Join-Path $HOME '.pico-sdk\picotool\2.3.0\picotool\picotool.exe'
if(!(Test-Path -LiteralPath $picotool -PathType Leaf)){throw "Missing picotool: $picotool"}
$logs=Join-Path $here 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$log=Join-Path $logs "bb-irq0-v3-$stamp-console.txt"
Write-Host 'WARNING: FLASHING standalone synthetic IRQ0 test firmware now.'
Write-Host 'The running DOS firmware is replaced until you reflash your existing UF2.'
Write-Host "New UF2 sha256: $((Get-FileHash $uf2 -Algorithm SHA256).Hash)"
$dosUf2='C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.uf2'
if(Test-Path -LiteralPath $dosUf2){
  Write-Host "Existing DOS firmware UF2 (NOT a readback of Pico flash): $dosUf2"
  Write-Host "Existing DOS UF2 sha256: $((Get-FileHash $dosUf2 -Algorithm SHA256).Hash)"
}
& $picotool reboot -f -u 2>&1 | Out-Host
Start-Sleep -Milliseconds 1200
& $picotool load -v -x $uf2 2>&1 | Out-Host
if($LASTEXITCODE -ne 0){throw "picotool load failed ($LASTEXITCODE)"}
Write-Host "=== Waiting for Pico CDC: $Port ==="
$deadline=(Get-Date).AddSeconds(30)
do{
 $found=Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue | Where-Object {
  $_.DeviceID -eq $Port -and $_.PNPDeviceID -match 'VID_2E8A'
 } | Select-Object -First 1
 if(!$found){Start-Sleep -Milliseconds 250}
}until($found -or (Get-Date) -ge $deadline)
if(!$found){throw "Pico CDC port $Port not found"}
$serial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
$serial.DtrEnable=$true
$serial.ReadTimeout=100
$captured=''
try{
 $serial.Open()
 $end=(Get-Date).AddSeconds($Seconds)
 while((Get-Date) -lt $end){
  $chunk=$serial.ReadExisting()
  if($chunk){
   Write-Host -NoNewline $chunk
   [System.IO.File]::AppendAllText($log,$chunk)
   $captured+=$chunk
   if($captured.Length -gt 200000){$captured=$captured.Substring($captured.Length-200000)}
   if($captured.Contains('[bb-irq0-v3] COMPLETE')){break}
  }
  Start-Sleep -Milliseconds 50
 }
}finally{
 if($serial.IsOpen){$serial.Close()}
 $serial.Dispose()
}
Write-Host "`nRAW LOG: $log"
if($captured -match '\[bb-irq0-v3\] COMPLETE[^\r\n]*result=PASS'){
 Write-Host 'DEVICE V3 PASS'
 exit 0
}
Write-Host 'DEVICE V3 did not report PASS; inspect the RAW LOG above.'
exit 1
