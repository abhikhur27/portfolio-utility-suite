function Get-SuiteRepoRoot {
    param([string]$CurrentPath)

    return Split-Path -Parent (Split-Path -Parent $CurrentPath)
}

function Get-SuiteManifest {
    param([string]$RepoRoot)

    $manifestPath = Join-Path $RepoRoot "tool-manifest.json"
    if (-not (Test-Path $manifestPath)) {
        throw "Could not find tool-manifest.json at $manifestPath"
    }

    return Get-Content $manifestPath | ConvertFrom-Json
}

function Get-ToolCommand {
    param([string]$CommandName)

    return Get-Command $CommandName -ErrorAction SilentlyContinue
}

function Get-ToolCommandPath {
    param([string]$CommandName)

    $command = Get-ToolCommand -CommandName $CommandName
    if (-not $command) {
        return $null
    }

    if ($command.Source) {
        return $command.Source
    }

    return $command.Name
}

function Get-CommandVersionText {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @("--version")
    )

    if (-not $FilePath) {
        return $null
    }

    try {
        $versionOutput = & $FilePath @Arguments 2>&1 | Select-Object -First 1
        if ($versionOutput) {
            return ($versionOutput.ToString()).Trim()
        }
    }
    catch {
        return $null
    }

    return $null
}

function Get-StackRuntimeStatus {
    param([string]$Stack)

    switch ($Stack) {
        "python" {
            $path = Get-ToolCommandPath -CommandName "python"
            return [pscustomobject]@{
                Stack = $Stack
                Available = [bool]$path
                Command = if ($path) { "python" } else { $null }
                Detail = if ($path) { $path } else { "python not found on PATH" }
                Version = Get-CommandVersionText -FilePath $path
            }
        }
        "node" {
            $path = Get-ToolCommandPath -CommandName "node"
            return [pscustomobject]@{
                Stack = $Stack
                Available = [bool]$path
                Command = if ($path) { "node" } else { $null }
                Detail = if ($path) { $path } else { "node not found on PATH" }
                Version = Get-CommandVersionText -FilePath $path
            }
        }
        "rust" {
            $path = Get-ToolCommandPath -CommandName "cargo"
            return [pscustomobject]@{
                Stack = $Stack
                Available = [bool]$path
                Command = if ($path) { "cargo" } else { $null }
                Detail = if ($path) { $path } else { "cargo not found on PATH" }
                Version = Get-CommandVersionText -FilePath $path
            }
        }
        "dotnet" {
            $path = Get-ToolCommandPath -CommandName "dotnet"
            return [pscustomobject]@{
                Stack = $Stack
                Available = [bool]$path
                Command = if ($path) { "dotnet" } else { $null }
                Detail = if ($path) { $path } else { "dotnet not found on PATH" }
                Version = Get-CommandVersionText -FilePath $path
            }
        }
        "go" {
            $path = Get-ToolCommandPath -CommandName "go"
            return [pscustomobject]@{
                Stack = $Stack
                Available = [bool]$path
                Command = if ($path) { "go" } else { $null }
                Detail = if ($path) { $path } else { "go not found on PATH" }
                Version = Get-CommandVersionText -FilePath $path
            }
        }
        "java" {
            $path = Get-ToolCommandPath -CommandName "javac"
            return [pscustomobject]@{
                Stack = $Stack
                Available = [bool]$path
                Command = if ($path) { "javac" } else { $null }
                Detail = if ($path) { $path } else { "javac not found on PATH" }
                Version = Get-CommandVersionText -FilePath $path
            }
        }
        "powershell" {
            $path = Get-ToolCommandPath -CommandName "powershell"
            return [pscustomobject]@{
                Stack = $Stack
                Available = [bool]$path
                Command = if ($path) { "powershell" } else { $null }
                Detail = if ($path) { $path } else { "powershell not found on PATH" }
                Version = Get-CommandVersionText -FilePath $path -Arguments @("-NoProfile", "-Command", '$PSVersionTable.PSVersion.ToString()')
            }
        }
        "cpp" {
            $gppPath = Get-ToolCommandPath -CommandName "g++"
            if ($gppPath) {
                return [pscustomobject]@{
                    Stack = $Stack
                    Available = $true
                    Command = "g++"
                    Detail = $gppPath
                    Version = Get-CommandVersionText -FilePath $gppPath
                }
            }

            $zigPath = Get-ToolCommandPath -CommandName "zig"
            if ($zigPath) {
                return [pscustomobject]@{
                    Stack = $Stack
                    Available = $true
                    Command = "zig c++"
                    Detail = $zigPath
                    Version = Get-CommandVersionText -FilePath $zigPath -Arguments @("version")
                }
            }

            return [pscustomobject]@{
                Stack = $Stack
                Available = $false
                Command = $null
                Detail = "Neither g++ nor zig was found on PATH"
                Version = $null
            }
        }
        default {
            return [pscustomobject]@{
                Stack = $Stack
                Available = $false
                Command = $null
                Detail = "Unsupported stack '$Stack'"
                Version = $null
            }
        }
    }
}

function Resolve-CppCompilerInvocation {
    $gppPath = Get-ToolCommandPath -CommandName "g++"
    if ($gppPath) {
        return [pscustomobject]@{
            FilePath = $gppPath
            Arguments = @()
            Label = "g++"
        }
    }

    $zigPath = Get-ToolCommandPath -CommandName "zig"
    if ($zigPath) {
        return [pscustomobject]@{
            FilePath = $zigPath
            Arguments = @("c++")
            Label = "zig c++"
        }
    }

    return $null
}

function Get-SuiteDoctorReport {
    param(
        [object[]]$Manifest,
        [string]$RepoRoot
    )

    $stackStatuses = @($Manifest.stack | Sort-Object -Unique | ForEach-Object { Get-StackRuntimeStatus -Stack $_ })
    $stackIndex = @{}
    foreach ($status in $stackStatuses) {
        $stackIndex[$status.Stack] = $status
    }

    $toolRows = foreach ($tool in ($Manifest | Sort-Object name)) {
        $toolPath = Join-Path $RepoRoot $tool.path
        $runtime = $stackIndex[$tool.stack]
        [pscustomobject]@{
            Tool = $tool.name
            Stack = $tool.stack
            Runnable = [bool]($runtime -and $runtime.Available -and (Test-Path $toolPath))
            Runtime = if ($runtime) { $runtime.Command } else { $null }
            ToolPath = $tool.path
            Detail = if (-not (Test-Path $toolPath)) {
                "Missing tool path"
            } elseif (-not $runtime.Available) {
                $runtime.Detail
            } else {
                "Ready"
            }
        }
    }

    $readyCount = @($toolRows | Where-Object { $_.Runnable }).Count
    $blockedCount = $toolRows.Count - $readyCount

    return [pscustomobject]@{
        GeneratedAt = (Get-Date).ToString("o")
        RepoRoot = $RepoRoot
        Summary = [pscustomobject]@{
            ToolCount = $toolRows.Count
            ReadyToolCount = $readyCount
            BlockedToolCount = $blockedCount
            StackCount = $stackStatuses.Count
        }
        Toolchains = $stackStatuses
        Tools = $toolRows
    }
}

function Convert-DoctorReportToMarkdown {
    param([object]$Report)

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# Portfolio Utility Suite Doctor")
    $lines.Add("")
    $lines.Add("- Generated: $($Report.GeneratedAt)")
    $lines.Add("- Repo root: $($Report.RepoRoot)")
    $lines.Add("- Ready tools: $($Report.Summary.ReadyToolCount) / $($Report.Summary.ToolCount)")
    $lines.Add("- Blocked tools: $($Report.Summary.BlockedToolCount)")
    $lines.Add("")
    $lines.Add("## Toolchains")
    $lines.Add("")
    $lines.Add("| Stack | Available | Command | Version | Detail |")
    $lines.Add("| --- | --- | --- | --- | --- |")
    foreach ($row in $Report.Toolchains) {
        $lines.Add("| $($row.Stack) | $(if ($row.Available) { 'yes' } else { 'no' }) | $($row.Command) | $($row.Version) | $($row.Detail) |")
    }
    $lines.Add("")
    $lines.Add("## Tool Readiness")
    $lines.Add("")
    $lines.Add("| Tool | Stack | Runnable | Runtime | Detail |")
    $lines.Add("| --- | --- | --- | --- | --- |")
    foreach ($row in $Report.Tools) {
        $lines.Add("| $($row.Tool) | $($row.Stack) | $(if ($row.Runnable) { 'yes' } else { 'no' }) | $($row.Runtime) | $($row.Detail) |")
    }

    return ($lines -join [Environment]::NewLine)
}

