param([ValidateSet('Install','Restore')][string]$Mode='Install')
$ErrorActionPreference='Stop'
$dest='C:\blitz86_v2\src\be_t2.c'
$expected='3717230f1971afc6389eb9aef977f468466ed554d63fd8924e614cf98877f5b1'
$replacement='57368ec728a5b28523782678d395dc4be6300550124335d277af86bac74d7e2a'
$backup=Join-Path $PSScriptRoot 'be_t2.c.before_p1b'
if (!(Test-Path $dest)) { throw "Missing $dest" }
if ($Mode -eq 'Install') {
    $actual=(Get-FileHash $dest -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected -and $actual -ne $replacement) {
        throw "Unexpected version $actual. This package requires Page-Zero v1, and will not overwrite this file."
    }
    if (!(Test-Path $backup)) { Copy-Item $dest $backup -Force }
    Copy-Item (Join-Path $PSScriptRoot 'src\be_t2.c') $dest -Force
    Write-Host 'Installed P1b full be_t2.c (preserves P1 Page-Zero and EA Imm12).'
} else {
    if (!(Test-Path $backup)) { throw "Missing backup $backup" }
    Copy-Item $backup $dest -Force
    Write-Host 'Restored pre-P1b be_t2.c.'
}
