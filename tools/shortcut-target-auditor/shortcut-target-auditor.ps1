[CmdletBinding()]
param(
  [string[]]$Roots,
  [string]$JsonOut,
  [string]$MarkdownOut,
  [int]$Top = 12
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-DefaultRoots {
  $candidates = @(
    (Join-Path $env:USERPROFILE 'Desktop'),
    (Join-Path $env:PUBLIC 'Desktop'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
    (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'),
    (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Startup')
  )

  return $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
}

function Normalize-TargetKey {
  param([string]$Target)

  if ([string]::IsNullOrWhiteSpace($Target)) {
    return '[missing-target]'
  }

  return $Target.Trim().ToLowerInvariant()
}

function Get-UrlValue {
  param(
    [string[]]$Lines,
    [string]$Name
  )

  foreach ($line in $Lines) {
    if ($line -match "^\s*$([regex]::Escape($Name))\s*=(.*)$") {
      return $matches[1].Trim()
    }
  }

  return ''
}

function Resolve-ShortcutRecord {
  param(
    [System.IO.FileInfo]$File,
    $Shell
  )

  $extension = $File.Extension.ToLowerInvariant()
  if ($extension -eq '.lnk') {
    $shortcut = $Shell.CreateShortcut($File.FullName)
    $target = [string]$shortcut.TargetPath
    $exists = $false
    if (-not [string]::IsNullOrWhiteSpace($target)) {
      $exists = Test-Path -LiteralPath $target
    }

    return [PSCustomObject]@{
      kind = 'lnk'
      path = $File.FullName
      target = $target
      arguments = [string]$shortcut.Arguments
      workingDirectory = [string]$shortcut.WorkingDirectory
      iconLocation = [string]$shortcut.IconLocation
      exists = $exists
    }
  }

  if ($extension -eq '.url') {
    $lines = Get-Content -LiteralPath $File.FullName
    $url = Get-UrlValue -Lines $lines -Name 'URL'
    $icon = Get-UrlValue -Lines $lines -Name 'IconFile'
    $isFileUrl = $url -match '^(?i:file://)'
    $resolvedTarget = if ($isFileUrl) {
      try {
        ([System.Uri]$url).LocalPath
      } catch {
        ''
      }
    } else {
      $url
    }

    $exists = if ($isFileUrl -and $resolvedTarget) {
      Test-Path -LiteralPath $resolvedTarget
    } elseif ($url) {
      $true
    } else {
      $false
    }

    return [PSCustomObject]@{
      kind = 'url'
      path = $File.FullName
      target = [string]$resolvedTarget
      rawUrl = [string]$url
      arguments = ''
      workingDirectory = ''
      iconLocation = [string]$icon
      exists = $exists
    }
  }

  return $null
}

function Test-IsStartupPath {
  param([string]$Path)

  return $Path -match '(?i)\\start menu\\programs\\startup\\'
}

function Test-IsNetworkTarget {
  param(
    [string]$Target,
    [string]$RawUrl
  )

  if ($RawUrl -match '^(?i:file://)') {
    return $true
  }

  if ([string]::IsNullOrWhiteSpace($Target)) {
    return $false
  }

  return $Target.StartsWith('\\')
}

function Get-RiskFlags {
  param(
    $Record,
    [int]$DuplicateCount
  )

  $flags = New-Object System.Collections.Generic.List[string]

  if (-not $Record.target) {
    $flags.Add('missing-target')
  }
  if (-not $Record.exists) {
    $flags.Add('broken-target')
  }
  if ($Record.isStartup) {
    $flags.Add('startup-entry')
  }
  if ($Record.isNetwork) {
    $flags.Add('network-target')
  }
  if ($Record.kind -eq 'url' -and $Record.rawUrl -match '^(?i:file://)') {
    $flags.Add('file-url')
  }
  if ($DuplicateCount -gt 1) {
    $flags.Add('duplicate-target')
  }

  return $flags
}

if (-not $Roots -or -not @($Roots).Count) {
  $Roots = Get-DefaultRoots
}

$resolvedRoots = @($Roots | Where-Object { $_ } | ForEach-Object {
  try {
    (Resolve-Path -LiteralPath $_).Path
  } catch {
    $null
  }
} | Where-Object { $_ } | Select-Object -Unique)

if (-not @($resolvedRoots).Count) {
  throw 'No valid shortcut roots were found. Pass -Roots explicitly.'
}

$shell = New-Object -ComObject WScript.Shell
$files = @(foreach ($root in $resolvedRoots) {
  Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.lnk', '.url' }
})

$records = @(foreach ($file in $files) {
  Resolve-ShortcutRecord -File $file -Shell $shell
})

$duplicateLookup = @{}
foreach ($group in ($records | Group-Object { Normalize-TargetKey $_.target })) {
  $duplicateLookup[$group.Name] = $group.Count
}

$enriched = foreach ($record in $records) {
  $duplicateCount = $duplicateLookup[(Normalize-TargetKey $record.target)]
  $isNetwork = $false
  if (@($record.PSObject.Properties.Match('rawUrl')).Count) {
    $isNetwork = Test-IsNetworkTarget -Target $record.target -RawUrl $record.rawUrl
  } else {
    $isNetwork = Test-IsNetworkTarget -Target $record.target -RawUrl ''
  }

  $item = [PSCustomObject]@{
    kind = $record.kind
    path = $record.path
    target = $record.target
    rawUrl = if (@($record.PSObject.Properties.Match('rawUrl')).Count) { $record.rawUrl } else { '' }
    arguments = $record.arguments
    workingDirectory = $record.workingDirectory
    iconLocation = $record.iconLocation
    exists = [bool]$record.exists
    isStartup = Test-IsStartupPath -Path $record.path
    isNetwork = [bool]$isNetwork
    duplicateCount = [int]$duplicateCount
    flags = @()
  }

  $item.flags = @(Get-RiskFlags -Record $item -DuplicateCount $duplicateCount)
  $item
}

$summary = [PSCustomObject]@{
  scannedAt = (Get-Date).ToString('s')
  roots = $resolvedRoots
  shortcutCount = @($enriched).Count
  brokenCount = @($enriched | Where-Object { $_.flags -contains 'broken-target' }).Count
  startupCount = @($enriched | Where-Object { $_.flags -contains 'startup-entry' }).Count
  networkCount = @($enriched | Where-Object { $_.flags -contains 'network-target' }).Count
  duplicateCount = @($enriched | Where-Object { $_.flags -contains 'duplicate-target' }).Count
}

$ranked = $enriched | Sort-Object `
  @{ Expression = { if ($_.flags -contains 'broken-target') { 0 } else { 1 } } }, `
  @{ Expression = { if ($_.flags -contains 'startup-entry') { 0 } else { 1 } } }, `
  @{ Expression = { -1 * $_.duplicateCount } }, `
  path

$duplicateGroups = @($enriched |
  Group-Object { Normalize-TargetKey $_.target } |
  Where-Object { $_.Count -gt 1 -and $_.Name -ne '[missing-target]' } |
  Sort-Object Count -Descending |
  ForEach-Object {
    [PSCustomObject]@{
      target = $_.Group[0].target
      count = $_.Count
      shortcuts = $_.Group.path
    }
  })

$summary | Format-List
Write-Host ''
Write-Host 'Top findings:' -ForegroundColor Cyan
$ranked |
  Select-Object -First $Top kind, exists, isStartup, isNetwork, duplicateCount, @{ Name = 'flags'; Expression = { ($_.flags -join ', ') } }, path, target |
  Format-Table -Wrap -AutoSize

if ($JsonOut) {
  $jsonDir = Split-Path -Parent $JsonOut
  if ($jsonDir) {
    New-Item -ItemType Directory -Path $jsonDir -Force | Out-Null
  }

  [PSCustomObject]@{
    summary = $summary
    findings = $ranked
    duplicateGroups = $duplicateGroups
  } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $JsonOut
}

if ($MarkdownOut) {
  $markdownDir = Split-Path -Parent $MarkdownOut
  if ($markdownDir) {
    New-Item -ItemType Directory -Path $markdownDir -Force | Out-Null
  }

  $topRows = @($ranked | Select-Object -First $Top)
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add('# Shortcut Target Audit')
  $lines.Add('')
  $lines.Add("Scanned at: $($summary.scannedAt)")
  $lines.Add('')
  $lines.Add('## Summary')
  $lines.Add('')
  $lines.Add("- Roots: $($summary.roots -join ', ')")
  $lines.Add("- Shortcuts scanned: $($summary.shortcutCount)")
  $lines.Add("- Broken targets: $($summary.brokenCount)")
  $lines.Add("- Startup entries: $($summary.startupCount)")
  $lines.Add("- Network-backed targets: $($summary.networkCount)")
  $lines.Add("- Duplicate-target rows: $($summary.duplicateCount)")
  $lines.Add('')
  $lines.Add('## Top Findings')
  $lines.Add('')

  foreach ($row in $topRows) {
    $lines.Add("### $($row.path)")
    $lines.Add("- Kind: $($row.kind)")
    $lines.Add("- Target: $($row.target)")
    $lines.Add("- Exists: $($row.exists)")
    $lines.Add("- Startup: $($row.isStartup)")
    $lines.Add("- Network: $($row.isNetwork)")
    $lines.Add("- Duplicate count: $($row.duplicateCount)")
    $lines.Add("- Flags: $(if (@($row.flags).Count) { $row.flags -join ', ' } else { 'none' })")
    $lines.Add('')
  }

  if (@($duplicateGroups).Count) {
    $lines.Add('## Duplicate Target Groups')
    $lines.Add('')
    foreach ($group in $duplicateGroups) {
      $lines.Add("### $($group.target)")
      $lines.Add("- Shortcut count: $($group.count)")
      foreach ($shortcutPath in $group.shortcuts) {
        $lines.Add("- $shortcutPath")
      }
      $lines.Add('')
    }
  }

  $lines -join "`r`n" | Set-Content -LiteralPath $MarkdownOut
}
