[CmdletBinding()]
param(
    [string]$MicroDOS = 'C:\microDOS',
    [string]$Blitz86 = 'C:\blitz86_v2'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$MicroDOS = (Resolve-Path $MicroDOS).Path
$Blitz86 = (Resolve-Path $Blitz86).Path
$out = Join-Path $root 'build-host'
$log = Join-Path $out 'bridge-probe-msvc.log'
$exe = Join-Path $out 'bb_bridge_smoke.exe'
$cmdFile = Join-Path $out 'bridge-probe-build.cmd'
New-Item -ItemType Directory -Force -Path $out | Out-Null
foreach ($path in @("$root\tests\bridge_smoke.c", "$root\src\bb_b86_bridge.c", "$MicroDOS\include\microdos\runtime.h", "$Blitz86\include\b86.h", "$Blitz86\src\interp.c")) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing source/header: $path" }
}
# Like microDOS's host build, discover Visual Studio instead of assuming
# the calling PowerShell session has already run a developer environment.
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$install = $null
if (Test-Path -LiteralPath $vswhere) {
    $install = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($LASTEXITCODE -ne 0) { $install = $null }
}
if (-not $install) {
    foreach ($edition in @('Community','Professional','Enterprise','BuildTools')) {
        $candidate = Join-Path ${env:ProgramFiles} "Microsoft Visual Studio\2022\$edition"
        if (Test-Path -LiteralPath (Join-Path $candidate 'VC\Auxiliary\Build\vcvarsall.bat')) { $install = $candidate; break }
    }
}
if (-not $install) { throw 'Visual Studio C++ build tools not found (vswhere/VS2022). Install MSVC x64 tools and Windows SDK.' }
$vcvars = Join-Path ([string]($install | Select-Object -First 1)) 'VC\Auxiliary\Build\vcvarsall.bat'
if (-not (Test-Path -LiteralPath $vcvars)) { throw "vcvarsall.bat not found: $vcvars" }
# Quotes in these rooted local paths would make cmd.exe unsafe/ambiguous.
foreach ($p in @($root,$MicroDOS,$Blitz86,$out,$vcvars)) {
    if ($p -match '["&|<>^%!]') { throw "Unsupported cmd metacharacter in path: $p" }
}
# Open Watcom's INCLUDE/LIB may exist in the parent shell. Strip those
# entirely *before* vcvarsall populates the MSVC/Windows SDK search paths.
# This process is isolated to this child cmd.exe and never changes the caller.
$lines = @(
    '@echo off',
    'setlocal EnableExtensions DisableDelayedExpansion',
    'set "INCLUDE="',
    'set "LIB="',
    'set "LIBPATH="',
    ('call "{0}" x64 >nul' -f $vcvars),
    'if errorlevel 1 (echo [blitzBUS] FAIL vcvarsall & exit /b 2)',
    'where cl.exe',
    'if errorlevel 1 exit /b 3',
    ('cl.exe /nologo /c /TC /std:c11 /W3 /O2 /I"{0}\src" /I"{1}\include" /I"{2}\include" /Fo:"{3}\bb_bridge_smoke.obj" "{0}\tests\bridge_smoke.c"' -f $root,$MicroDOS,$Blitz86,$out),
    'if errorlevel 1 (echo [blitzBUS] FAIL compiling bridge_smoke.c & exit /b 4)',
    ('cl.exe /nologo /c /TC /std:c11 /W3 /O2 /I"{0}\src" /I"{1}\include" /I"{2}\include" /Fo:"{3}\bb_b86_bridge.obj" "{0}\src\bb_b86_bridge.c"' -f $root,$MicroDOS,$Blitz86,$out),
    'if errorlevel 1 (echo [blitzBUS] FAIL compiling bb_b86_bridge.c & exit /b 4)',
    ('cl.exe /nologo /c /TC /std:c11 /W3 /O2 /I"{0}\src" /I"{1}\include" /I"{2}\include" /Fo:"{3}\bb_b86_interp.obj" "{2}\src\interp.c"' -f $root,$MicroDOS,$Blitz86,$out),
    'if errorlevel 1 (echo [blitzBUS] FAIL compiling blitz86 interp.c & exit /b 4)',
    ('link.exe /nologo /OUT:"{0}" "{1}\bb_bridge_smoke.obj" "{1}\bb_b86_bridge.obj" "{1}\bb_b86_interp.obj"' -f $exe,$out),
    'if errorlevel 1 (echo [blitzBUS] FAIL linking bridge smoke & exit /b 4)',
        'if errorlevel 1 (echo [blitzBUS] FAIL bridge smoke & exit /b 5)',
    'echo [blitzBUS] bridge_probe=PASS backend=NOT_ENABLED jit_guest_insns=0',
    'exit /b 0'
)
# cmd.exe's /Fo directory form needs the directory to exist, which is ensured.
[IO.File]::WriteAllLines($cmdFile, $lines, [Text.Encoding]::ASCII)
Write-Host "[blitzBUS] Visual Studio: $install"
Write-Host "[blitzBUS] Build log: $log"
# Redirect streams to files so Windows PowerShell 5.1 does not turn compiler
# stderr lines into terminating NativeCommandError exceptions.
$stdout = Join-Path $out 'bridge-probe-stdout.txt'
$stderr = Join-Path $out 'bridge-probe-stderr.txt'
$process = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d','/c',('"{0}"' -f $cmdFile)) -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$exitCode = $process.ExitCode
$run = @((Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue), (Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue))
$run | ForEach-Object { Write-Host ([string]$_) }
$run | Out-File -LiteralPath $log -Encoding utf8
if ($exitCode -ne 0) { throw "Bridge probe failed (exit=$exitCode). Log: $log" }
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Probe reported success but EXE missing: $exe" }
