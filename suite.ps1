param(
    [ValidateSet("list", "info", "run", "check", "doctor")]
    [string]$Action = "list",
    [string]$Tool,
    [string[]]$ToolArgs = @(),
    [string]$ArgumentLine,
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

function Get-PythonEntrypoint {
    param($Record, [string]$ToolPath)

    $entryTokens = @($Record.entrypoint -split "\s+")
    foreach ($token in $entryTokens) {
        if ($token -like "*.py" -and (Test-Path (Join-Path $ToolPath $token))) {
            return $token
        }
    }

    $candidates = Get-ChildItem -Path $ToolPath -Filter *.py -File |
        Where-Object { $_.Name -notlike "test_*.py" -and $_.Name -notlike "*_test.py" } |
        Sort-Object Name
    if ($candidates.Count -eq 0) {
        throw "No Python entrypoint found for $($Record.name)"
    }

    return $candidates[0].Name
}

function Resolve-ToolArguments {
    param(
        [string[]]$ArgsArray,
        [string]$ArgsLine
    )

    if ($ArgsLine) {
        $matches = [regex]::Matches($ArgsLine, '''[^'']*''|"[^"]*"|\S+')
        return @(
            $matches | ForEach-Object {
                $value = $_.Value
                if (
                    ($value.StartsWith("'") -and $value.EndsWith("'")) -or
                    ($value.StartsWith('"') -and $value.EndsWith('"'))
                ) {
                    $value.Substring(1, $value.Length - 2)
                } else {
                    $value
                }
            }
        )
    }

    return $ArgsArray
}

function Invoke-Tool {
    param($Record, [string[]]$Arguments)

    $toolPath = Join-Path $repoRoot $Record.path
    if (-not (Test-Path $toolPath)) {
        throw "Tool path does not exist: $toolPath"
    }

    Push-Location $toolPath
    try {
        switch ($Record.stack) {
            "python" {
                $script = Get-PythonEntrypoint -Record $Record -ToolPath $toolPath
                & python $script @Arguments
            }
            "node" {
                & node "cli.js" @Arguments
            }
            "rust" {
                & cargo run -- @Arguments
            }
            "dotnet" {
                $project = Get-ChildItem -Filter *.csproj -File | Select-Object -First 1
                if (-not $project) {
                    throw "No .csproj file found for $($Record.name)"
                }

                & dotnet run --project $project.FullName -- @Arguments
            }
            "powershell" {
                $script = Get-ChildItem -Filter *.ps1 -File | Select-Object -First 1
                if (-not $script) {
                    throw "No PowerShell script found for $($Record.name)"
                }

                & powershell -ExecutionPolicy Bypass -File $script.FullName @Arguments
            }
            "go" {
                & go run . @Arguments
            }
            "java" {
                $source = Join-Path $toolPath "src\DatasetSplitAuditor.java"
                if (-not (Test-Path $source)) {
                    throw "Expected Java source file at $source"
                }

                & javac $source
                if ($LASTEXITCODE -ne 0) {
                    exit $LASTEXITCODE
                }

                & java -cp (Join-Path $toolPath "src") "DatasetSplitAuditor" @Arguments
            }
            "cpp" {
                $compiler = Resolve-CppCompilerInvocation
                if (-not $compiler) {
                    throw "A C++ compiler is required to run C++ tools. Install g++ or zig."
                }

                $source = Join-Path $toolPath "main.cpp"
                $artifactDir = Join-Path $toolPath "artifacts"
                $binaryPath = Join-Path $artifactDir $Record.name
                if (-not (Test-Path $source)) {
                    throw "Expected C++ source file at $source"
                }

                New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
                $compileArgs = @()
                $compileArgs += $compiler.Arguments
                $compileArgs += @($source, "-std=c++17", "-O2", "-o", $binaryPath)
                & $compiler.FilePath @compileArgs
                if ($LASTEXITCODE -ne 0) {
                    exit $LASTEXITCODE
                }

                $runnableBinary = if (Test-Path "$binaryPath.exe") { "$binaryPath.exe" } elseif (Test-Path $binaryPath) { $binaryPath } else { $null }
                if (-not $runnableBinary) {
                    throw "Compiled C++ artifact not found at $binaryPath or $binaryPath.exe"
                }

                & $runnableBinary @Arguments
            }
            default {
                throw "Unsupported stack '$($Record.stack)' for $($Record.name)"
            }
        }

        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    finally {
        Pop-Location
    }
}

switch ($Action) {
    "list" {
        $manifest | Sort-Object name | Format-Table name, stack, path -AutoSize
    }
    "info" {
        if (-not $Tool) {
            throw "The info action requires -Tool <tool-name>"
        }

        $record = Get-ToolRecord -Name $Tool
        $toolPath = Join-Path $repoRoot $record.path
        $readmePath = Join-Path $toolPath "README.md"

        [pscustomobject]@{
            name = $record.name
            stack = $record.stack
            path = $record.path
            entrypoint = $record.entrypoint
            readme = $readmePath
        } | Format-List
    }
    "run" {
        if (-not $Tool) {
            throw "The run action requires -Tool <tool-name>"
        }

        $resolvedArguments = Resolve-ToolArguments -ArgsArray $ToolArgs -ArgsLine $ArgumentLine
        Invoke-Tool -Record (Get-ToolRecord -Name $Tool) -Arguments $resolvedArguments
    }
    "check" {
        $scriptPath = Join-Path $repoRoot "scripts\check.ps1"
        if (-not (Test-Path $scriptPath)) {
            throw "Shared checker not found at $scriptPath"
        }

        if ($Tool) {
            & $scriptPath -Tool $Tool
        } else {
            & $scriptPath
        }
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "doctor" {
        $report = Get-SuiteDoctorReport -Manifest $manifest -RepoRoot $repoRoot

        switch ($DoctorFormat) {
            "json" {
                $content = $report | ConvertTo-Json -Depth 6
            }
            "markdown" {
                $content = Convert-DoctorReportToMarkdown -Report $report
            }
            default {
                Write-Host "Portfolio Utility Suite Doctor"
                Write-Host "Ready tools: $($report.Summary.ReadyToolCount) / $($report.Summary.ToolCount)"
                Write-Host ""
                $report.Toolchains | Sort-Object Stack | Format-Table Stack, Available, Command, Version, Detail -AutoSize
                Write-Host ""
                $report.Tools | Sort-Object Tool | Format-Table Tool, Stack, Runnable, Runtime, Detail -AutoSize
            }
        }

        if ($DoctorFormat -ne "table") {
            if ($OutputPath) {
                $parent = Split-Path -Parent $OutputPath
                if ($parent) {
                    New-Item -ItemType Directory -Path $parent -Force | Out-Null
                }
                Set-Content -Path $OutputPath -Value $content
                Write-Host "Wrote doctor report to $OutputPath"
            } else {
                $content
            }
        } elseif ($OutputPath) {
            $markdown = Convert-DoctorReportToMarkdown -Report $report
            $parent = Split-Path -Parent $OutputPath
            if ($parent) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }
            Set-Content -Path $OutputPath -Value $markdown
            Write-Host "Wrote doctor report to $OutputPath"
        }
    }
}
