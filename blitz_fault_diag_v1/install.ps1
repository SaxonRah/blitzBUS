param(
    [ValidateSet('Install','Restore','Check')]
    [string]$Mode = 'Check',
    [string]$BlitzBUS = 'C:\blitzBUS'
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'src\bb_live.c'
$target = Join-Path $BlitzBUS 'src\bb_live.c'
$backup = "$target.before_v50_faultdiag"
$expectedOld = '4e654e4712cb3d4ed29c086b52f2a491d2a782d735baa32f73ebef56f9210735'
$expectedNew = 'ff4886d44c5353992ba63729b6ea69d35f6bb28e06d582cbf8b06c0d7d450855'
function HashOf($p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }
if (!(Test-Path $target)) { throw "Target not found: $target" }
$current = HashOf $target
Write-Host "Current bb_live.c SHA256: $current"
switch ($Mode) {
  'Check' {
    if ($current -eq $expectedOld) { Write-Host 'Compatible source: ready to install.' }
    elseif ($current -eq $expectedNew) { Write-Host 'Already installed.' }
    else { Write-Host 'Source differs from archived version; installation intentionally blocked.' }
  }
  'Install' {
    if ((HashOf $source) -ne $expectedNew) { throw 'Package checksum mismatch.' }
    if ($current -eq $expectedNew) { Write-Host 'Already installed.'; break }
    if ($current -ne $expectedOld) { throw 'Source revision mismatch. Nothing changed. Provide current C:\blitzBUS\src\bb_live.c for a compatible complete replacement.' }
    if (Test-Path $backup) { throw "Backup already exists; refusing to overwrite: $backup" }
    Copy-Item -LiteralPath $target -Destination $backup
    Copy-Item -LiteralPath $source -Destination $target -Force
    if ((HashOf $target) -ne $expectedNew) { Copy-Item -LiteralPath $backup -Destination $target -Force; throw 'Installed checksum mismatch; restored backup.' }
    Write-Host "Installed full replacement. Backup: $backup"
  }
  'Restore' {
    if (!(Test-Path $backup)) { throw "Backup not found: $backup" }
    if ($current -ne $expectedNew) { throw 'Current source differs from package; refusing to overwrite.' }
    Copy-Item -LiteralPath $backup -Destination $target -Force
    Write-Host 'Restored previous source.'
  }
}
