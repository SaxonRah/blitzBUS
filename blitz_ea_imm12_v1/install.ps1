param(
    [ValidateSet('Off','On')][string]$Mode = 'On',
    [string]$Blitz86 = 'C:\blitz86_v2'
)
$ErrorActionPreference='Stop'
$source = Join-Path $PSScriptRoot 'src\be_t2.c'
$target = Join-Path $Blitz86 'src\be_t2.c'
$originalHash = '4f0fe19f5f95dd38dfe8de23f815c36c97abd05f55ab36dce6fa0ab7877f0e6b'
if (!(Test-Path $target)) { throw "Missing $target" }
$actualHash = (Get-FileHash $target -Algorithm SHA256).Hash.ToLowerInvariant()
$newHash=(Get-FileHash $source -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $originalHash -and $actualHash -ne $newHash) { throw "Source differs from captured snapshot. No changes made. Actual hash $actualHash" }
if ($actualHash -eq $originalHash) {
    $backup = "$target.before_ea_imm12_v1"
    if (Test-Path $backup) { throw "Backup already exists: $backup. No changes made." }
    Copy-Item $target $backup
    Copy-Item $source $target
    Write-Host "Installed complete be_t2.c; backup: $backup"
} else { Write-Host 'Complete be_t2.c already installed.' }
Write-Host "Mode: $Mode"
Write-Host 'The compiler macro is configured by an explicit CMake target compile definition.'
Write-Host 'Run the configuration command from README.md; this script does not edit CMakeLists.txt.'
