param(
    [string]$Tool,
    [ValidateSet("python", "node", "rust", "dotnet", "go", "java", "powershell", "cpp")]
    [string]$Stack,
    [ValidateSet("host", "portable", "windows")]
    [string]$Shard = "host",
    [ValidateSet("build", "smoke")]
    [string]$Mode = "build"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $repoRoot "scripts\common.ps1")
$manifest = Get-SuiteManifest -RepoRoot $repoRoot

if ($Tool) {
    $manifest = $manifest | Where-Object { $_.name -eq $Tool }
    if (-not $manifest) {
        throw "Unknown tool '$Tool'"
    }
}

if ($Stack) {
    $manifest = @($manifest | Where-Object { $_.stack -eq $Stack })
}

if ($Shard -ne "host") {
    $targetPlatform = if ($Shard -eq "portable") { "all" } else { "windows" }
    $manifest = @($manifest | Where-Object {
        $checkPlatform = if ($Mode -eq "smoke") {
            Get-SuiteSmokePlatform -Record $_
        } else {
            Get-SuiteToolPlatform -Record $_
        }
        $checkPlatform -eq $targetPlatform
    })
}

if (@($manifest).Count -eq 0) {
    throw "No tools matched the requested check filters (tool='$Tool', stack='$Stack', shard='$Shard', mode='$Mode')."
}

function Invoke-LoggedCommand {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    Write-Host "[$Label] $FilePath $($Arguments -join ' ')"
    Push-Location $WorkingDirectory
    $commandExitCode = 0
    try {
        if (Test-Path $FilePath) {
            & $FilePath @Arguments | Out-Host
        } else {
            $command = Get-Command $FilePath -ErrorAction Stop
            $target = if ($command.Source) { $command.Source } else { $command.Name }
            & $target @Arguments | Out-Host
        }
        $commandExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    finally {
        Pop-Location
    }

    return $commandExitCode
}

function Test-PowerShellSyntax {
    param([string]$Path)

    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null
    return $errors
}

$results = New-Object System.Collections.Generic.List[object]

foreach ($toolRecord in $manifest) {
    $toolPath = Join-Path $repoRoot $toolRecord.path
    $readmePath = Join-Path $toolPath "README.md"

    if (-not (Test-Path $readmePath)) {
        $results.Add([pscustomobject]@{
            Tool = $toolRecord.name
            Stack = $toolRecord.stack
            Status = "FAIL"
            Detail = "Missing README.md"
        })
        continue
    }

    $platformSupported = if ($Mode -eq "smoke") {
        Test-SuiteSmokePlatformSupport -Record $toolRecord
    } else {
        Test-SuitePlatformSupport -Record $toolRecord
    }
    if (-not $platformSupported) {
        $requiredPlatform = if ($Mode -eq "smoke") {
            Get-SuiteSmokePlatform -Record $toolRecord
        } else {
            Get-SuiteToolPlatform -Record $toolRecord
        }
        $results.Add([pscustomobject]@{
            Tool = $toolRecord.name
            Stack = $toolRecord.stack
            Status = "SKIP"
            Detail = "Platform '$requiredPlatform' is not available on this host"
        })
        continue
    }

    try {
        $status = "PASS"
        $detail = $null
        if ($Mode -eq "smoke") {
            $arguments = @($toolRecord.smoke.arguments | ForEach-Object { [string]$_ })
            Write-Host "[$($toolRecord.name)] smoke: $($toolRecord.smoke.description)"
            $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            Invoke-SuiteTool -Record $toolRecord -RepoRoot $repoRoot -Arguments $arguments -SmokeCheck
            $stopwatch.Stop()
            $detail = "Runtime smoke passed in $([math]::Round($stopwatch.Elapsed.TotalSeconds, 2))s"
        } else {
            switch ($toolRecord.stack) {
            "python" {
                $pythonFiles = Get-ChildItem -Path $toolPath -Filter *.py -File
                foreach ($file in $pythonFiles) {
                    $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "python" -Arguments @("-m", "py_compile", $file.FullName) -WorkingDirectory $toolPath
                    if ($exitCode -ne 0) {
                        throw "py_compile failed for $($file.Name)"
                    }
                }
                $testFiles = @(Get-ChildItem -Path $toolPath -Filter "test*.py" -File -Recurse)
                $testDirectories = @($testFiles | ForEach-Object { $_.DirectoryName } | Sort-Object -Unique)
                foreach ($testDirectory in $testDirectories) {
                    $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "python" -Arguments @("-m", "unittest", "discover", "-s", $testDirectory, "-p", "test*.py") -WorkingDirectory $toolPath
                    if ($exitCode -ne 0) {
                        throw "Python unittest discovery failed"
                    }
                }
                $detail = "Compiled $($pythonFiles.Count) Python file(s); ran $($testFiles.Count) test file(s)"
            }
            "node" {
                $packageJson = Join-Path $toolPath "package.json"
                if (Test-Path $packageJson) {
                    $package = Get-Content $packageJson | ConvertFrom-Json
                    if ($package.scripts.check) {
                        $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "npm" -Arguments @("run", "check") -WorkingDirectory $toolPath
                        if ($exitCode -ne 0) {
                            throw "npm run check failed"
                        }
                    }
                    if ($package.scripts.test) {
                        $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "npm" -Arguments @("test") -WorkingDirectory $toolPath
                        if ($exitCode -ne 0) {
                            throw "npm test failed"
                        }
                    }
                    $detail = "Ran package check/test scripts"
                } else {
                    $nodeFiles = Get-ChildItem -Path $toolPath -Filter *.js -File
                    foreach ($file in $nodeFiles) {
                        $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "node" -Arguments @("--check", $file.FullName) -WorkingDirectory $toolPath
                        if ($exitCode -ne 0) {
                            throw "node --check failed for $($file.Name)"
                        }
                    }
                    $detail = "Checked $($nodeFiles.Count) JavaScript file(s)"
                }
            }
            "rust" {
                $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "cargo" -Arguments @("test") -WorkingDirectory $toolPath
                if ($exitCode -ne 0) {
                    throw "cargo test failed"
                }
                $detail = "cargo test passed"
            }
            "dotnet" {
                $project = Get-ChildItem -Path $toolPath -Filter *.csproj -File | Select-Object -First 1
                if (-not $project) {
                    throw "Missing .csproj"
                }
                $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "dotnet" -Arguments @("build", $project.FullName) -WorkingDirectory $toolPath
                if ($exitCode -ne 0) {
                    throw "dotnet build failed"
                }
                $detail = "dotnet build passed"
            }
            "powershell" {
                $script = Get-ChildItem -Path $toolPath -Filter *.ps1 -File | Select-Object -First 1
                if (-not $script) {
                    throw "Missing .ps1 entrypoint"
                }
                $errors = Test-PowerShellSyntax -Path $script.FullName
                if ($errors.Count -gt 0) {
                    throw ($errors | ForEach-Object { $_.Message } | Select-Object -First 1)
                }
                $detail = "PowerShell parse passed"
            }
            "go" {
                $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "go" -Arguments @("test", "./...") -WorkingDirectory $toolPath
                if ($exitCode -ne 0) {
                    throw "go test failed"
                }
                $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "go" -Arguments @("build", ".") -WorkingDirectory $toolPath
                if ($exitCode -ne 0) {
                    throw "go build failed"
                }
                $detail = "go test and build passed"
            }
            "java" {
                $source = Join-Path $toolPath "src\DatasetSplitAuditor.java"
                if (-not (Test-Path $source)) {
                    throw "Missing DatasetSplitAuditor.java"
                }
                $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath "javac" -Arguments @($source) -WorkingDirectory $toolPath
                if ($exitCode -ne 0) {
                    throw "javac failed"
                }
                $detail = "javac passed"
            }
            "cpp" {
                $compiler = Resolve-CppCompilerInvocation
                if (-not $compiler) {
                    $status = "SKIP"
                    $detail = "No supported C++ compiler found (g++ or zig)"
                    break
                }
                $source = Join-Path $toolPath "main.cpp"
                if (-not (Test-Path $source)) {
                    throw "Missing main.cpp"
                }
                $artifactDir = Join-Path $toolPath "artifacts"
                $binaryName = if ($env:OS -eq "Windows_NT") { "$($toolRecord.name).exe" } else { $toolRecord.name }
                $binaryPath = Join-Path $artifactDir $binaryName
                New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
                $compileArgs = @()
                $compileArgs += $compiler.Arguments
                $compileArgs += @($source, "-std=c++17", "-O2", "-o", $binaryPath)
                $exitCode = Invoke-LoggedCommand -Label $toolRecord.name -FilePath $compiler.FilePath -Arguments $compileArgs -WorkingDirectory $toolPath
                if ($exitCode -ne 0) {
                    throw "$($compiler.Label) build failed"
                }
                $detail = "$($compiler.Label) build passed"
            }
            default {
                throw "Unsupported stack '$($toolRecord.stack)'"
            }
            }
        }

        $results.Add([pscustomobject]@{
            Tool = $toolRecord.name
            Stack = $toolRecord.stack
            Status = $status
            Detail = $detail
        })
    }
    catch {
        $results.Add([pscustomobject]@{
            Tool = $toolRecord.name
            Stack = $toolRecord.stack
            Status = "FAIL"
            Detail = $_.Exception.Message
        })
    }
}

Write-Host ""
Write-Host "Portfolio Utility Suite $Mode results"
$results | Sort-Object Tool | Format-Table -AutoSize

$failed = @($results | Where-Object { $_.Status -eq "FAIL" })
if ($failed.Count -gt 0) {
    Write-Error "$($failed.Count) tool check(s) failed."
}
