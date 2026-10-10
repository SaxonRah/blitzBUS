param([string]$Logs = 'C:\blitzBUS\logs')
$ErrorActionPreference='Stop'
Get-ChildItem -LiteralPath $Logs -Filter 'bb-live-*-console.txt' -File |
  Sort-Object Name |
  ForEach-Object {
    $f = $_
    $raw = Get-Content -LiteralPath $f.FullName
    $fault = @($raw | Where-Object { $_ -match '\[bb-v42-diag\] PREVIOUS RUN HARDFAULT' })
    $rich = @($raw | Where-Object { $_ -match '\[bb-v(45-diag|50-fault)\]' })
    if ($fault.Count -gt 0) {
      Write-Host "`n=== $($f.Name) ==="
      $fault | ForEach-Object { Write-Host $_ }
      $rich | ForEach-Object { Write-Host $_ }
    }
  }
