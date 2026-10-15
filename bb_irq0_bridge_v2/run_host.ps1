[CmdletBinding()]
param(
    [string]$MicroDOS='C:\microDOS',
    [string]$Blitz86='C:\blitz86_v2',
    [switch]$NoBuildMicroDOS,
    [switch]$PrepareOnly
)
$ErrorActionPreference='Stop'
$project=$PSScriptRoot
$MicroDOS=(Resolve-Path -LiteralPath $MicroDOS).Path
$Blitz86=(Resolve-Path -LiteralPath $Blitz86).Path
$out=Join-Path $project 'build-host'
if(-not (Test-Path (Join-Path $Blitz86 'src\interp.c'))){throw "Missing blitz86 interpreter: $Blitz86"}
if(-not (Test-Path (Join-Path $MicroDOS 'src\runtime\runtime.c'))){throw "Missing microDOS runtime: $MicroDOS"}
Write-Host '=== Preflight ==='
Write-Host "microDOS=$MicroDOS"
Write-Host "blitz86=$Blitz86"
Write-Host 'No Pico, COM port, source edits or disk-image writes.'
& python (Join-Path $project 'prepare_sources.py') selftest
if($LASTEXITCODE -ne 0){throw 'prepare_sources selftest failed'}
if(-not $NoBuildMicroDOS) {
    & cmake --build (Join-Path $MicroDOS 'build-host') --config Release --target microdos_runtime
    if($LASTEXITCODE -ne 0){throw 'microDOS runtime build failed'}
}
& python (Join-Path $project 'prepare_sources.py') prepare --blitz $Blitz86 --out $out --msvc
if($LASTEXITCODE -ne 0){throw 'Unable to stage local blitz86 source'}
if($PrepareOnly){Write-Host 'PREPARE ONLY PASS; no compilation or execution';exit 0}
& cmake -S $project -B $out -G 'Visual Studio 17 2022' -A x64 "-DMICRODOS_ROOT=$MicroDOS" "-DBLITZ86_ROOT=$Blitz86"
if($LASTEXITCODE -ne 0){throw 'CMake configure failed'}
& cmake --build $out --config Release --target bb_irq0_bridge
if($LASTEXITCODE -ne 0){throw 'Actual blitz86 interpreter compilation failed'}
$exe=Join-Path $out 'Release\bb_irq0_bridge.exe'
if(-not (Test-Path -LiteralPath $exe)){throw "Missing host test exe: $exe"}
& $exe
if($LASTEXITCODE -ne 0){throw "IRQ0 host bridge failed: exit $LASTEXITCODE"}
Write-Host 'HOST BRIDGE REGRESSION PASS: microDOS + actual local blitz86 interpreter; no JIT/Pico/disk use.'
