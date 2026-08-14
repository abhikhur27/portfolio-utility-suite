param(
    [ValidateSet("list", "info", "run", "check", "doctor")]
    [string]$Action = "list",
    [string]$Tool,
    [string[]]$ToolArgs = @(),
    [string]$ArgumentLine,
    [ValidateSet("build", "smoke")]
    [string]$CheckMode = "build",
    [ValidateSet("table", "json", "markdown")]
    [string]$DoctorFormat = "table",
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $repoRoot "scripts\common.ps1")
$manifest = Get-SuiteManifest -RepoRoot $repoRoot

function Get-ToolRecord {
    param([string]$Name)

    $record = $manifest | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if (-not $record) {
        $available = ($manifest.name | Sort-Object) -join ", "
        throw "Unknown tool '$Name'. Available tools: $available"
    }
    return $record
}

switch ($Action) {
    "list" {
        $manifest | Sort-Object name | ForEach-Object {
            [pscustomobject]@{
                name = $_.name
                stack = $_.stack
                platform = if ($_.PSObject.Properties.Name -contains "platform") { $_.platform } else { "all" }
                path = $_.path
            }
        } | Format-Table name, stack, platform, path -AutoSize
    }
    "info" {
        if (-not $Tool) {
            throw "The info action requires -Tool <tool-name>"
        }

        $record = Get-ToolRecord -Name $Tool
        $toolPath = Join-Path $repoRoot $record.path
        [pscustomobject]@{
            name = $record.name
            stack = $record.stack
            platform = if ($record.PSObject.Properties.Name -contains "platform") { $record.platform } else { "all" }
            path = $record.path
            entrypoint = $record.entrypoint
            smoke = $record.smoke.description
            smokeArguments = @($record.smoke.arguments) -join " "
            readme = Join-Path $toolPath "README.md"
        } | Format-List
    }
    "run" {
        if (-not $Tool) {
            throw "The run action requires -Tool <tool-name>"
        }

        $resolvedArguments = Resolve-SuiteToolArguments -ArgsArray $ToolArgs -ArgsLine $ArgumentLine
        Invoke-SuiteTool -Record (Get-ToolRecord -Name $Tool) -RepoRoot $repoRoot -Arguments $resolvedArguments
    }
    "check" {
        $scriptPath = Join-Path $repoRoot "scripts\check.ps1"
        if ($Tool) {
            & $scriptPath -Tool $Tool -Mode $CheckMode
        } else {
            & $scriptPath -Mode $CheckMode
        }
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "doctor" {
        $report = Get-SuiteDoctorReport -Manifest $manifest -RepoRoot $repoRoot

        switch ($DoctorFormat) {
            "json" { $content = $report | ConvertTo-Json -Depth 6 }
            "markdown" { $content = Convert-DoctorReportToMarkdown -Report $report }
            default {
                Write-Host "Portfolio Utility Suite Doctor"
                Write-Host "Ready tools: $($report.Summary.ReadyToolCount) / $($report.Summary.ToolCount)"
                Write-Host "Smoke checks configured: $($report.Summary.SmokeCheckCount) / $($report.Summary.ToolCount)"
                Write-Host ""
                $report.Toolchains | Sort-Object Stack | Format-Table Stack, Available, Command, Version, Detail -AutoSize
                Write-Host ""
                $report.Tools | Sort-Object Tool | Format-Table Tool, Stack, Platform, Runnable, Runtime, SmokeCheck, Detail -AutoSize
            }
        }

        if ($DoctorFormat -ne "table") {
            if ($OutputPath) {
                $parent = Split-Path -Parent $OutputPath
                if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
                Set-Content -Path $OutputPath -Value $content
                Write-Host "Wrote doctor report to $OutputPath"
            } else {
                $content
            }
        } elseif ($OutputPath) {
            $markdown = Convert-DoctorReportToMarkdown -Report $report
            $parent = Split-Path -Parent $OutputPath
            if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            Set-Content -Path $OutputPath -Value $markdown
            Write-Host "Wrote doctor report to $OutputPath"
        }
    }
}
