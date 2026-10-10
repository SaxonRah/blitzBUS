param([ValidateSet('Install','Restore')][string]$Mode='Install')
$ErrorActionPreference='Stop'
$sourceDir=Join-Path $PSScriptRoot 'src'
$backupDir=Join-Path $PSScriptRoot 'backup'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$files=@('be_t2.c','jit.c','b86.h')
$expected_be_t2_c = '029842eedb78dc17a8b9df23cd733061c239bb5c66781db857e337d4e3fc35d1'
$new_be_t2_c = '3717230f1971afc6389eb9aef977f468466ed554d63fd8924e614cf98877f5b1'
$expected_jit_c = '4f2d1178f710fca86784f6e79e2c638a697b44022554b60bb23a414984ef617b'
$new_jit_c = '9403d6a16cde211ba2179304d13e0dd00b423a82f8e87827663e7bc800693459'
$expected_b86_h = 'f723eaa30a607dc3a6d625c47121c5e666f82ab65b618195bd5561990ce6f419'
$new_b86_h = 'c1a219cbc1188e7c2c8d86b712d702fbde1b72e1239e743b4f0b0665ca539f0d'
$specs=@(
  @{Name='be_t2.c';Dest='C:\blitz86_v2\src\be_t2.c';Before=$expected_be_t2_c;After=$new_be_t2_c},
  @{Name='jit.c';Dest='C:\blitz86_v2\src\jit.c';Before=$expected_jit_c;After=$new_jit_c},
  @{Name='b86.h';Dest='C:\blitz86_v2\include\b86.h';Before=$expected_b86_h;After=$new_b86_h}
)
foreach($s in $specs) {
    $dst=$s.Dest; $bk=Join-Path $backupDir $s.Name
    if($Mode -eq 'Install') {
        if(!(Test-Path $dst)){throw "Missing file: $dst"}
        $actual=(Get-FileHash $dst -Algorithm SHA256).Hash.ToLowerInvariant()
        if($actual -ne $s.Before -and $actual -ne $s.After){throw "Unexpected local revision: $dst. Not overwriting. SHA=$actual"}
        if(!(Test-Path $bk)) {Copy-Item $dst $bk -Force}
    } else {
        if(!(Test-Path $bk)) {throw "Missing backup: $bk"}
    }
}
foreach($s in $specs) {
    $dst=$s.Dest
    if($Mode -eq 'Install') {Copy-Item (Join-Path $sourceDir $s.Name) $dst -Force}
    else {Copy-Item (Join-Path $backupDir $s.Name) $dst -Force}
    Write-Host "$Mode $dst"
}
Write-Host 'Completed. Build flag B86_OPT_PAGE_ZERO=1 must be set on blitzbus_pico_b86_dos for the fast path.'
