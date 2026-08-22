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

    $manifest = Get-Content $manifestPath | ConvertFrom-Json
    Test-SuiteManifest -Manifest $manifest -RepoRoot $RepoRoot
    return $manifest
}

function Test-SuiteManifest {
    param(
        [object[]]$Manifest,
        [string]$RepoRoot
    )

    $supportedStacks = @("python", "node", "rust", "dotnet", "go", "java", "powershell", "cpp")
    $supportedPlatforms = @("all", "windows")
    $errors = New-Object System.Collections.Generic.List[string]
    $names = @{}

    foreach ($record in @($Manifest)) {
        $name = [string]$record.name
        if ([string]::IsNullOrWhiteSpace($name)) {
            $errors.Add("A manifest record is missing its name.")
            continue
        }
        if ($names.ContainsKey($name)) {
            $errors.Add("Duplicate tool name '$name'.")
        }
        $names[$name] = $true

        if ($supportedStacks -notcontains [string]$record.stack) {
            $errors.Add("$name uses unsupported stack '$($record.stack)'.")
        }
        if ([string]::IsNullOrWhiteSpace([string]$record.entrypoint)) {
            $errors.Add("$name is missing its entrypoint.")
        }
        if ([string]::IsNullOrWhiteSpace([string]$record.path) -or [System.IO.Path]::IsPathRooted([string]$record.path)) {
            $errors.Add("$name must use a relative tool path.")
        } else {
            $toolPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $record.path))
            $rootPath = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
            if (-not $toolPath.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                $errors.Add("$name points outside the suite repository.")
            } elseif (-not (Test-Path -LiteralPath $toolPath -PathType Container)) {
                $errors.Add("$name tool path does not exist: $($record.path)")
            }
        }

        $platform = if ($record.PSObject.Properties.Name -contains "platform") { [string]$record.platform } else { "all" }
        if ($supportedPlatforms -notcontains $platform) {
            $errors.Add("$name uses unsupported platform '$platform'.")
        }
        if (-not ($record.PSObject.Properties.Name -contains "smoke")) {
            $errors.Add("$name is missing smoke-check metadata.")
        } else {
            if (-not ($record.smoke.PSObject.Properties.Name -contains "arguments")) {
                $errors.Add("$name smoke metadata is missing arguments.")
            }
            if ([string]::IsNullOrWhiteSpace([string]$record.smoke.description)) {
                $errors.Add("$name smoke metadata is missing a description.")
            }
            $smokePlatform = if ($record.smoke.PSObject.Properties.Name -contains "platform") {
                [string]$record.smoke.platform
            } else {
                $platform
            }
            if ($supportedPlatforms -notcontains $smokePlatform) {
                $errors.Add("$name uses unsupported smoke platform '$smokePlatform'.")
            }
        }
    }

    if ($errors.Count -gt 0) {
        throw "Invalid tool-manifest.json:`n- $($errors -join "`n- ")"
    }
}

function Test-SuiteHostPlatform {
    param([string]$Platform)

    if ($Platform -eq "all") {
        return $true
    }
    return $Platform -eq "windows" -and $env:OS -eq "Windows_NT"
}

function Get-SuiteToolPlatform {
    param($Record)

    if ($Record.PSObject.Properties.Name -contains "platform") {
        return [string]$Record.platform
    }
    return "all"
}

function Get-SuiteSmokePlatform {
    param($Record)

    if ($Record.smoke.PSObject.Properties.Name -contains "platform") {
        return [string]$Record.smoke.platform
    }
    return Get-SuiteToolPlatform -Record $Record
}

function Test-SuitePlatformSupport {
    param($Record)

    return Test-SuiteHostPlatform -Platform (Get-SuiteToolPlatform -Record $Record)
}

function Test-SuiteSmokePlatformSupport {
    param($Record)

    return Test-SuiteHostPlatform -Platform (Get-SuiteSmokePlatform -Record $Record)
}

function Resolve-SuiteToolArguments {
    param(
        [string[]]$ArgsArray,
        [string]$ArgsLine
    )

    if ($ArgsLine) {
        $matches = [regex]::Matches($ArgsLine, '''[^'']*''|"[^\"]*"|\S+')
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

    return @($ArgsArray)
}

function ConvertTo-SuiteArgumentString {
    param($Value)

    if ($Value -is [datetime]) {
        return $Value.ToString("o", [System.Globalization.CultureInfo]::InvariantCulture)
    }
    if ($Value -is [datetimeoffset]) {
        return $Value.ToString("o", [System.Globalization.CultureInfo]::InvariantCulture)
    }
    return [string]$Value
}

function Get-SuitePythonEntrypoint {
    param($Record, [string]$ToolPath)

    $entryTokens = @($Record.entrypoint -split "\s+")
    foreach ($token in $entryTokens) {
        if ($token -like "*.py" -and (Test-Path (Join-Path $ToolPath $token))) {
            return $token
        }
    }

    $candidates = @(Get-ChildItem -Path $ToolPath -Filter *.py -File |
        Where-Object { $_.Name -notlike "test_*.py" -and $_.Name -notlike "*_test.py" } |
        Sort-Object Name)
    if ($candidates.Count -eq 0) {
        throw "No Python entrypoint found for $($Record.name)"
    }

    return $candidates[0].Name
}

function Invoke-SuiteTool {
    param(
        $Record,
        [string]$RepoRoot,
        [string[]]$Arguments = @(),
        [switch]$SmokeCheck
    )

    $platformSupported = if ($SmokeCheck) {
        Test-SuiteSmokePlatformSupport -Record $Record
    } else {
        Test-SuitePlatformSupport -Record $Record
    }
    if (-not $platformSupported) {
        $requiredPlatform = if ($SmokeCheck) {
            Get-SuiteSmokePlatform -Record $Record
        } else {
            Get-SuiteToolPlatform -Record $Record
        }
        throw "$($Record.name) only supports this operation on platform '$requiredPlatform'."
    }

    $toolPath = Join-Path $RepoRoot $Record.path
    Push-Location $toolPath
    try {
        $global:LASTEXITCODE = 0
        switch ($Record.stack) {
            "python" {
                $script = Get-SuitePythonEntrypoint -Record $Record -ToolPath $toolPath
                & python $script @Arguments | Out-Host
            }
            "node" {
                & node "cli.js" @Arguments | Out-Host
            }
            "rust" {
                & cargo run -- @Arguments | Out-Host
            }
            "dotnet" {
                $project = Get-ChildItem -Path $toolPath -Filter *.csproj -File | Select-Object -First 1
                if (-not $project) {
                    throw "No .csproj file found for $($Record.name)"
                }
                & dotnet run --project $project.FullName -- @Arguments | Out-Host
            }
            "powershell" {
                $script = Get-ChildItem -Path $toolPath -Filter *.ps1 -File | Select-Object -First 1
                if (-not $script) {
                    throw "No PowerShell script found for $($Record.name)"
                }
                & powershell -NoProfile -ExecutionPolicy Bypass -File $script.FullName @Arguments | Out-Host
            }
            "go" {
                & go run . @Arguments | Out-Host
            }
            "java" {
                $source = Join-Path $toolPath "src\DatasetSplitAuditor.java"
                & javac $source | Out-Host
                if ($LASTEXITCODE -eq 0) {
                    & java -cp (Join-Path $toolPath "src") "DatasetSplitAuditor" @Arguments | Out-Host
                }
            }
            "cpp" {
                $compiler = Resolve-CppCompilerInvocation
                if (-not $compiler) {
                    throw "A C++ compiler is required to run C++ tools. Install g++ or zig."
                }
                $source = Join-Path $toolPath "main.cpp"
                $artifactDir = Join-Path $toolPath "artifacts"
                $binaryName = if ($env:OS -eq "Windows_NT") { "$($Record.name).exe" } else { $Record.name }
                $binaryPath = Join-Path $artifactDir $binaryName
                New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
                $compileArgs = @($compiler.Arguments) + @($source, "-std=c++17", "-O2", "-o", $binaryPath)
                & $compiler.FilePath @compileArgs | Out-Host
                if ($LASTEXITCODE -eq 0) {
                    if (-not (Test-Path $binaryPath)) {
                        throw "Compiled C++ artifact not found for $($Record.name)."
                    }
                    & $binaryPath @Arguments | Out-Host
                }
            }
            default {
                throw "Unsupported stack '$($Record.stack)' for $($Record.name)"
            }
        }

        $commandExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        if ($commandExitCode -ne 0) {
            throw "$($Record.name) exited with code $commandExitCode."
        }
    }
    finally {
        Pop-Location
    }
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
        $platformSupported = Test-SuitePlatformSupport -Record $tool
        $smokePlatform = Get-SuiteSmokePlatform -Record $tool
        $smokePlatformSupported = Test-SuiteSmokePlatformSupport -Record $tool
        [pscustomobject]@{
            Tool = $tool.name
            Stack = $tool.stack
            Platform = Get-SuiteToolPlatform -Record $tool
            Runnable = [bool]($platformSupported -and $runtime -and $runtime.Available -and (Test-Path $toolPath))
            Runtime = if ($runtime) { $runtime.Command } else { $null }
            ToolPath = $tool.path
            SmokeCheck = if ($tool.PSObject.Properties.Name -contains "smoke") { "configured" } else { "missing" }
            SmokePlatform = $smokePlatform
            SmokeRunnable = [bool]($smokePlatformSupported -and $runtime -and $runtime.Available -and (Test-Path $toolPath))
            Detail = if (-not (Test-Path $toolPath)) {
                "Missing tool path"
            } elseif (-not $platformSupported) {
                "Unsupported on this host"
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
            SmokeCheckCount = @($toolRows | Where-Object { $_.SmokeCheck -eq "configured" }).Count
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
    $lines.Add("- Smoke checks configured: $($Report.Summary.SmokeCheckCount) / $($Report.Summary.ToolCount)")
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
    $lines.Add("| Tool | Stack | Platform | Runnable | Runtime | Smoke platform | Smoke runnable | Detail |")
    $lines.Add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    foreach ($row in $Report.Tools) {
        $lines.Add("| $($row.Tool) | $($row.Stack) | $($row.Platform) | $(if ($row.Runnable) { 'yes' } else { 'no' }) | $($row.Runtime) | $($row.SmokePlatform) | $(if ($row.SmokeRunnable) { 'yes' } else { 'no' }) | $($row.Detail) |")
    }

    return ($lines -join [Environment]::NewLine)
}
