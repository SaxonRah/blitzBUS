[CmdletBinding()]
param(
 [string]$MicroDos='C:\microDOS',
 [string]$Blitz86='C:\blitz86_v2',
 [string]$SdkPath='',
 [string]$ToolchainPath='',
 [string]$NinjaPath=''
)
$ErrorActionPreference='Stop'
$here=(Resolve-Path -LiteralPath $PSScriptRoot).Path
$cache=Join-Path $MicroDos 'build-pico\out\CMakeCache.txt'
function Cache-Value([string]$name) {
    if(!(Test-Path -LiteralPath $cache -PathType Leaf)){return ''}
    $pattern='^'+[regex]::Escape($name)+':[^=]*=(.*)$'
    foreach($line in [System.IO.File]::ReadLines($cache)) {
        if($line -match $pattern) {return $Matches[1]}
    }
    return ''
}
function SDK-OK([string]$candidate){
    return ((-not [string]::IsNullOrWhiteSpace($candidate)) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'pico_sdk_init.cmake') -PathType Leaf))
}
function Toolchain-OK([string]$candidate){
    return ((-not [string]::IsNullOrWhiteSpace($candidate)) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'bin\arm-none-eabi-gcc.exe') -PathType Leaf))
}
function Resolve-SDK {
    if($SdkPath) {
        if(!(SDK-OK $SdkPath)){throw "Invalid -SdkPath: $SdkPath (pico_sdk_init.cmake not found)"}
        return (Resolve-Path -LiteralPath $SdkPath).Path
    }
    $choices=@()
    $saved=Cache-Value 'PICO_SDK_PATH'
    if($saved){$choices+= $saved}
    if($env:PICO_SDK_PATH){$choices+= $env:PICO_SDK_PATH}
    $sdkRoot=Join-Path $HOME '.pico-sdk\sdk'
    if(Test-Path -LiteralPath $sdkRoot -PathType Container){
        $choices+= $sdkRoot
        $choices+= @(Get-ChildItem -LiteralPath $sdkRoot -Directory -ErrorAction SilentlyContinue |
                     Sort-Object Name -Descending | Select-Object -ExpandProperty FullName)
    }
    $choices+= @('C:\pico-sdk','C:\pico\pico-sdk')
    foreach($p in $choices) {if(SDK-OK $p){return (Resolve-Path -LiteralPath $p).Path}}
    throw "Could not find Pico SDK. Try: Get-ChildItem `"$sdkRoot`" -Directory. Then pass -SdkPath '<folder containing pico_sdk_init.cmake>'. The existing microDOS cache is: $cache"
}
function Resolve-Toolchain {
    if($ToolchainPath) {
        if(!(Toolchain-OK $ToolchainPath)){throw "Invalid -ToolchainPath: $ToolchainPath (bin/arm-none-eabi-gcc.exe missing)"}
        return (Resolve-Path -LiteralPath $ToolchainPath).Path
    }
    $choices=@()
    $saved=Cache-Value 'PICO_TOOLCHAIN_PATH'
    if($saved){$choices+=$saved}
    if($env:PICO_TOOLCHAIN_PATH){$choices+=$env:PICO_TOOLCHAIN_PATH}
    $savedCompiler=Cache-Value 'CMAKE_C_COMPILER'
    if($savedCompiler -and (Test-Path -LiteralPath $savedCompiler -PathType Leaf)) {
        $choices+= (Split-Path -Parent (Split-Path -Parent $savedCompiler))
    }
    $gcc=Get-Command arm-none-eabi-gcc.exe -ErrorAction SilentlyContinue
    if($gcc){$choices+= (Split-Path -Parent (Split-Path -Parent $gcc.Source))}
    $root=Join-Path $HOME '.pico-sdk\toolchain'
    if(Test-Path -LiteralPath $root -PathType Container){
        $choices+= $root
        $choices+= @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                     Sort-Object Name -Descending | Select-Object -ExpandProperty FullName)
    }
    foreach($p in $choices){if(Toolchain-OK $p){return (Resolve-Path -LiteralPath $p).Path}}
    throw "ARM GCC toolchain missing. Check the working microDOS cache ($cache) or specify -ToolchainPath '<folder containing bin/arm-none-eabi-gcc.exe>'."
}
function Resolve-Ninja {
    if($NinjaPath) {
        if(!(Test-Path -LiteralPath $NinjaPath -PathType Leaf)){throw "Invalid -NinjaPath: $NinjaPath"}
        return (Resolve-Path -LiteralPath $NinjaPath).Path
    }
    $choices=@()
    $saved=Cache-Value 'CMAKE_MAKE_PROGRAM'
    if($saved){$choices+= $saved}
    $ninja=Get-Command ninja.exe -ErrorAction SilentlyContinue
    if($ninja){$choices+= $ninja.Source}
    $root=Join-Path $HOME '.pico-sdk\ninja'
    if(Test-Path -LiteralPath $root -PathType Container){
        $choices+= (Join-Path $root 'ninja.exe')
        foreach($subdir in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                             Sort-Object Name -Descending)){
            $choices+= (Join-Path $subdir.FullName 'ninja.exe')
            $choices+= (Join-Path $subdir.FullName 'bin\ninja.exe')
        }
    }
    foreach($p in $choices){if($p -and (Test-Path -LiteralPath $p -PathType Leaf)){
        return (Resolve-Path -LiteralPath $p).Path
    }}
    throw 'Ninja not found. Use the existing Pico SDK Ninja (e.g. $HOME\.pico-sdk\ninja\<version>\ninja.exe) and pass -NinjaPath <path-to-ninja.exe>.'
}
foreach($p in @("$MicroDos\pico\pico_sdk_import.cmake",
                "$MicroDos\pico\b86_hw_alloc.c",
                "$Blitz86\include\b86.h",
                "$Blitz86\src\interp.c",
                "$Blitz86\src\jit.c",
                "$Blitz86\src\be_t2.c")) {
    if(!(Test-Path -LiteralPath $p -PathType Leaf)){throw "Missing prerequisite: $p"}
}
$sdk=Resolve-SDK
$toolchain=Resolve-Toolchain
$ninja=Resolve-Ninja
$picotoolCache=Cache-Value 'picotool_DIR'
if(!$picotoolCache -or !(Test-Path -LiteralPath $picotoolCache -PathType Container)){
    $picotoolCache=Join-Path $HOME '.pico-sdk\picotool\2.3.0\picotool'
}
$tracked=@("$MicroDos\pico\b86_hw_alloc.c","$Blitz86\include\b86.h",
           "$Blitz86\src\interp.c","$Blitz86\src\jit.c","$Blitz86\src\be_t2.c")
$before=@{}
foreach($p in $tracked){$before[$p]=(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash}
# Use a NEW dir: V3's existing build-pico cached the wrong Visual Studio
# generator. Do not delete or rewrite old builds.
$buildDir=Join-Path $here 'build-pico-ninja'
function Slash([string]$p) {return $p.Replace('\','/')}
Write-Host '=== WINFIX1: toolchain preflight ==='
Write-Host "Pico SDK:   $sdk"
Write-Host "ARM GCC:    $(Join-Path $toolchain 'bin\arm-none-eabi-gcc.exe')"
Write-Host "Ninja:      $ninja"
Write-Host "Build dir:  $buildDir"
Write-Host 'Generator:  Ninja (RP2350 cross-compiler, NOT Visual Studio/MSVC)'
try {
    $cmakeArgs=@('-S',$here,'-B',$buildDir,'-G','Ninja',
            "-DMD_ROOT=$(Slash $MicroDos)",
            "-DBLITZ86_ROOT=$(Slash $Blitz86)",
            "-DPICO_SDK_PATH=$(Slash $sdk)",
            "-DPICO_TOOLCHAIN_PATH=$(Slash $toolchain)",
            "-DCMAKE_MAKE_PROGRAM=$(Slash $ninja)",
            '-DCMAKE_SUPPRESS_REGENERATION=ON',
            '-DPICO_BOARD=pimoroni_pico_plus2_rp2350')
    if(Test-Path -LiteralPath $picotoolCache -PathType Container){
        $cmakeArgs+= "-Dpicotool_DIR=$(Slash $picotoolCache)"
    }
    Write-Host '=== WINFIX2: Ninja automatic regeneration disabled; CMake is configured explicitly by this script ==='
    Write-Host '=== V3: configure isolated Pico firmware ==='
    & cmake @cmakeArgs
    if($LASTEXITCODE -ne 0){throw "CMake configure failed ($LASTEXITCODE)"}
    Write-Host '=== V3: build native Thumb-2 JIT probe ==='
    & cmake --build $buildDir --target bb_irq0_pico_v3 --parallel 4
    if($LASTEXITCODE -ne 0){throw "CMake build failed ($LASTEXITCODE)"}
} finally {
    foreach($p in $tracked){
        $after=(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
        if($after -ne $before[$p]){throw "Source unexpectedly changed during build: $p"}
    }
}
$uf2=Join-Path $buildDir 'bb_irq0_pico_v3.uf2'
if(!(Test-Path -LiteralPath $uf2 -PathType Leaf)){throw "UF2 missing: $uf2"}
Write-Host '=== V3 BUILD PASS ==='
Write-Host "UF2: $uf2"
Write-Host 'No Pico flash, COM port, DOS source or disk-image writes.'
