# Save the proven RM3 62.5 build BEFORE installing PM0.
# All source copied as full files; no patches; no Git mutation.
param(
    [string]$BlitzBUS = 'C:\blitzBUS',
    [string]$Blitz86 = 'C:\blitz86_v2',
    [string]$Build = 'C:\microDOS\build-pico\out',
    [string]$Label = 'RM3_62_5'
)
$ErrorActionPreference = 'Stop'
$dest = Join-Path $BlitzBUS "milestones\$Label"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$firmwareNames = @('blitzbus_pico_b86_dos.elf','blitzbus_pico_b86_dos.uf2','blitzbus_pico_b86_dos.map')
foreach ($name in $firmwareNames) {
    $f=Join-Path $Build $name
    if (Test-Path -LiteralPath $f) { Copy-Item -LiteralPath $f -Destination $dest -Force }
    else { Write-Warning "Firmware build output missing: $f" }
}
$log = Join-Path $BlitzBUS 'logs\bb-live-20261013-193713-console.txt'
if (Test-Path -LiteralPath $log) { Copy-Item -LiteralPath $log -Destination $dest -Force }
$srcdest = Join-Path $dest 'blitz86_sources'
New-Item -ItemType Directory -Force -Path $srcdest | Out-Null
foreach ($folder in @('include','src','tests')) {
    $f=Join-Path $Blitz86 $folder
    if (Test-Path -LiteralPath $f) { Copy-Item -LiteralPath $f -Destination $srcdest -Recurse -Force }
}
$liveSrc=Join-Path $BlitzBUS 'src\bb_live.c'
if (Test-Path -LiteralPath $liveSrc) { Copy-Item -LiteralPath $liveSrc -Destination $dest -Force }
Get-ChildItem -LiteralPath $BlitzBUS -File -Filter 'bb_386*.py' |
    Copy-Item -Destination $dest -Force
$files=Get-ChildItem -LiteralPath $dest -Recurse -File
$files | Get-FileHash -Algorithm SHA256 |
    Select-Object @{N='File';E={$_.Path.Substring($dest.Length+1)}},Hash |
    Export-Csv -LiteralPath (Join-Path $dest 'SHA256.csv') -NoTypeInformation
Write-Host "Saved known-good RM3 milestone: $dest"
Write-Host 'Source files and build SHA256 hashes archived. Current working checkout unchanged.'
