[CmdletBinding()]
param(
    [string]$MicroDOS='C:\microDOS',
    [switch]$NoBuild
)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$MicroDOS=(Resolve-Path -LiteralPath $MicroDOS).Path
$hostBuild=Join-Path $MicroDOS 'build-host'
$runtime=Join-Path $hostBuild 'Release\microdos_runtime.lib'
if(!(Test-Path (Join-Path $MicroDOS 'include\microdos\runtime.h'))){throw "microDOS headers missing: $MicroDOS"}
if(!(Test-Path $hostBuild)){throw "No microDOS host CMake build directory: $hostBuild"}
if(!$NoBuild){
    & cmake --build $hostBuild --config Release --target microdos_runtime
    if($LASTEXITCODE -ne 0){throw 'microDOS runtime build failed'}
}
if(!(Test-Path $runtime)){throw "Missing runtime library: $runtime"}
$out=Join-Path $root 'build-host'
& cmake -S $root -B $out -G 'Visual Studio 17 2022' -A x64 "-DMICRODOS_ROOT=$MicroDOS"
if($LASTEXITCODE -ne 0){throw 'Host diagnostic configure failed'}
& cmake --build $out --config Release --target bb_irq0_roundtrip
if($LASTEXITCODE -ne 0){throw 'Host diagnostic build failed'}
$exe=Join-Path $out 'Release\bb_irq0_roundtrip.exe'
if(!(Test-Path $exe)){throw "Diagnostic EXE missing: $exe"}
& $exe
if($LASTEXITCODE -ne 0){throw "IRQ0 host roundtrip failed: exit $LASTEXITCODE"}
Write-Host 'HOST IRQ0 REGRESSION PASS: no Pico, COM5, or disk images accessed.'
