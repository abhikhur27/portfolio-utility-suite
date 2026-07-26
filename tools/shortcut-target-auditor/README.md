# Shortcut Target Auditor

Windows shortcut audit utility for finding broken `.lnk` / `.url` entries, duplicate launch points, startup-folder shortcuts, and risky network-backed targets.

## Why it exists

Shortcut folders get messy fast across Desktop, Start Menu, and Startup. Broken targets, duplicate launch points, and network shares can stick around long after apps move or uninstall. This tool turns that surface into one concrete audit instead of a manual click-through.

## Features

- Recursively scans one or more folders for `.lnk` and `.url` shortcuts.
- Resolves `.lnk` metadata through Windows Script Host.
- Flags:
  - broken targets
  - startup-folder entries
  - network-share targets
  - file-URL shortcuts
  - duplicate targets referenced by multiple shortcuts
- Prints a concise console summary.
- Exports the full audit as JSON.
- Exports a Markdown brief with the riskiest rows and duplicate groups.

## Usage

```powershell
powershell -ExecutionPolicy Bypass -File .\shortcut-target-auditor.ps1
```

Scan specific folders and export artifacts:

```powershell
powershell -ExecutionPolicy Bypass -File .\shortcut-target-auditor.ps1 `
  -Roots "$env:USERPROFILE\Desktop","$env:APPDATA\Microsoft\Windows\Start Menu\Programs" `
  -JsonOut .\artifacts\shortcut-audit.json `
  -MarkdownOut .\artifacts\shortcut-audit.md
```

## Output fields

- `kind`: `lnk` or `url`
- `path`: shortcut path
- `target`: resolved target path or URL
- `exists`: whether the target currently resolves
- `isStartup`: whether the shortcut lives in a startup folder
- `isNetwork`: whether the target points to a UNC path, mapped network path, or `file://` URL
- `duplicateCount`: how many shortcuts point to the same target
- `flags`: risk tags that make the row worth attention

## Sanity Check

This repo includes no external dependencies. A quick verification path is:

```powershell
$tmp = Join-Path $env:TEMP "shortcut-target-auditor-smoke"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $tmp | Out-Null
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $tmp "Notepad.lnk"))
$link.TargetPath = "$env:WINDIR\System32\notepad.exe"
$link.Save()
Set-Content -Path (Join-Path $tmp "Docs.url") -Value "[InternetShortcut]`nURL=https://learn.microsoft.com"
powershell -ExecutionPolicy Bypass -File .\shortcut-target-auditor.ps1 -Roots $tmp
```

## Portfolio Positioning

- Stack: PowerShell, Windows, CLI
- Category: desktop hygiene / launch-surface audit utility
- Honest claim: this is a practical Windows audit tool, not a browser mockup
