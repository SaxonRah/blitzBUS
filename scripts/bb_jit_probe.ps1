[CmdletBinding()]
param([string]$MicroDOS='C:\microDOS', [string]$Blitz86='C:\blitz86_v2',
      [string]$Port='COM5', [int]$Seconds=50, [switch]$NoFlash, [switch]$NoBuild)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$MicroDOS=(Resolve-Path $MicroDOS).Path
$Blitz86=(Resolve-Path $Blitz86).Path
$logs=Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$log=Join-Path $logs "bb-jitprobe-$stamp-console.txt"
$report=Join-Path $logs "bb-jitprobe-$stamp-report.json"
$target='blitzbus_b86_jit_probe'
$uf2=Join-Path $MicroDOS "build-pico\out\$target.uf2"
$flashRunner=Join-Path $Blitz86 'compare-auto\pico_flash_capture.ps1'
$record=[ordered]@{target=$target;run=$stamp;result='INCOMPLETE';jit_executed=$false;dos_integrated=$false;console=$log;error=''}
try {
    & python (Join-Path $PSScriptRoot 'install_jit_probe.py') --microdos $MicroDOS --blitz86 $Blitz86
    if($LASTEXITCODE -ne 0){throw 'JIT target installation failed'}
    if(-not $NoBuild){
        # This is the existing standard repo entry point, including SDK and host disk setup.
        & (Join-Path $MicroDOS 'md.bat') build pico
        if($LASTEXITCODE -ne 0){throw 'microDOS build failed'}
        & cmake --build (Join-Path $MicroDOS 'build-pico\out') --target $target
        if($LASTEXITCODE -ne 0){throw 'blitz86 JIT probe target build failed'}
    }
    if(!(Test-Path $uf2)){throw "UF2 missing: $uf2"}
    if(!(Test-Path $flashRunner)){throw "blitz86 capture runner missing: $flashRunner"}
    # Hashtable splatting binds each value to the named parameter. Array
    # splatting here incorrectly gave COM5 to -Seconds in Windows PowerShell.
    $captureParams = @{
        Firmware = $uf2
        Port     = $Port
        Log      = $log
        Seconds  = $Seconds
    }
    if($NoFlash){ $captureParams['NoFlash'] = $true }
    Write-Host "[blitzBUS] Capture: firmware=$uf2 port=$Port seconds=$Seconds noflash=$([bool]$NoFlash)"
    & $flashRunner @captureParams
    if($LASTEXITCODE -ne 0){throw 'Pico JIT capture failed'}
    $raw=Get-Content -Raw -LiteralPath $log
    $line=[regex]::Match($raw,'(?m)^\[b86-jit\] backend=blitz86-thumb2 retired=(\d+) blocks=(\d+)')
    if(-not $line.Success){throw 'Missing real JIT retired and block counters'}
    $retired=[uint64]$line.Groups[1].Value; $blocks=[uint64]$line.Groups[2].Value
    $record['retired']=$retired;$record['blocks']=$blocks
    if($retired -eq 0 -or $blocks -eq 0){throw 'JIT executed zero instructions or translated zero blocks'}
    if($raw -notmatch '\[b86-jit\] COMPLETE result=PASS'){throw 'Firmware did not report PASS'}
    $record['jit_executed']=$true
    $record['result']='PASS'
    Write-Host "[blitzBUS] JIT HARDWARE PROBE PASS retired=$retired blocks=$blocks"
} catch {
    $record['result']='FAIL';$record['error']=[string]$_
    Write-Host "[blitzBUS] FAIL: $_"
} finally {
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding UTF8
    Write-Host "CONSOLE: $log"
    Write-Host "REPORT:  $report"
}
if($record['result'] -ne 'PASS'){exit 1}
