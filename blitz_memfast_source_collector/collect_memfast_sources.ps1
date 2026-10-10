param(
    [string]$Blitz86 = 'C:\blitz86_v2',
    [string]$BlitzBUS = 'C:\blitzBUS',
    [string]$MicroDOS = 'C:\microDOS',
    [string]$Output = 'C:\blitzBUS\logs\memfast_source_snapshot.zip'
)
$ErrorActionPreference = 'Stop'
$stage = Join-Path $env:TEMP ('bb_memfast_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
    $manifest = New-Object System.Collections.Generic.List[string]
    $manifest.Add('blitzBUS guarded JIT memory fast path source snapshot')
    $manifest.Add(('Captured: ' + (Get-Date -Format o)))
    foreach ($entry in @(
        @{ Root=$Blitz86; Label='blitz86_v2'; Files=@('src\be_t2.c','src\jit.c','src\interp.c','include\blitz86.h','CMakeLists.txt') },
        @{ Root=$BlitzBUS; Label='blitzBUS'; Files=@('src\bb_b86_bridge.c','src\bb_b86_bridge.h','src\bb_live.c','src\bb_live.h') },
        @{ Root=$MicroDOS; Label='microDOS'; Files=@('include\microdos\x86.h','pico\CMakeLists.txt') }
    )) {
        foreach ($relative in $entry.Files) {
            $src = Join-Path $entry.Root $relative
            if (!(Test-Path -LiteralPath $src -PathType Leaf)) { $manifest.Add("MISSING $($entry.Label)/$relative"); continue }
            $dest = Join-Path (Join-Path $stage $entry.Label) $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
            Copy-Item -LiteralPath $src -Destination $dest
            $sha = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash
            $manifest.Add("$($entry.Label)/$relative SHA256=$sha bytes=$((Get-Item -LiteralPath $src).Length)")
        }
    }
    # Include additional memory mapping and JIT public headers without build artifacts.
    foreach ($relroot in @('include','src')) {
        $dir = Join-Path $Blitz86 $relroot
        if (!(Test-Path $dir)) {continue}
        Get-ChildItem -LiteralPath $dir -Filter '*.h' -File -Recurse | Where-Object { $_.FullName -notmatch '[\\/](build|generated|third_party)[\\/]' } | ForEach-Object {
            $relative = $_.FullName.Substring($Blitz86.Length).TrimStart('\','/')
            $dest = Join-Path (Join-Path $stage 'blitz86_v2') $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        }
    }
    if (Test-Path (Join-Path $Blitz86 '.git')) {
        $rev = & git -C $Blitz86 rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0) { $manifest.Add("blitz86_v2 Git HEAD=$rev") }
        $status = & git -C $Blitz86 status --short 2>$null
        $status | Set-Content -LiteralPath (Join-Path $stage 'blitz86_v2_git_status.txt')
    }
    $manifest | Set-Content -LiteralPath (Join-Path $stage 'MANIFEST.txt') -Encoding utf8
    $outputParent = Split-Path $Output -Parent
    if ($outputParent -and !(Test-Path $outputParent)) { New-Item -ItemType Directory -Force -Path $outputParent | Out-Null }
    if (Test-Path $Output) { throw "Output already exists, choose a new -Output: $Output" }
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $Output -CompressionLevel Optimal
    Write-Host "SOURCE SNAPSHOT CREATED: $Output"
    Write-Host 'No source files were modified.'
    Get-Content -LiteralPath (Join-Path $stage 'MANIFEST.txt')
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
