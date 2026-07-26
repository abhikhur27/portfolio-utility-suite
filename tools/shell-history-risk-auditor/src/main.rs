use std::env;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum RiskLevel {
    Low,
    Medium,
    High,
}

impl RiskLevel {
    fn label(self) -> &'static str {
        match self {
            RiskLevel::Low => "low",
            RiskLevel::Medium => "medium",
            RiskLevel::High => "high",
        }
    }
}

#[derive(Clone, Copy, Debug)]
enum ShellKind {
    PowerShell,
    Bash,
    Zsh,
    Fish,
    Nushell,
    Unknown,
}

impl ShellKind {
    fn label(self) -> &'static str {
        match self {
            ShellKind::PowerShell => "powershell",
            ShellKind::Bash => "bash",
            ShellKind::Zsh => "zsh",
            ShellKind::Fish => "fish",
            ShellKind::Nushell => "nushell",
            ShellKind::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug)]
struct HistoryEntry {
    source_path: PathBuf,
    shell: ShellKind,
    line_number: usize,
    command: String,
}

#[derive(Clone, Debug)]
struct RiskFinding {
    level: RiskLevel,
    label: String,
    reason: String,
    command: String,
    source_path: PathBuf,
    shell: ShellKind,
    line_number: usize,
}

#[derive(Clone, Debug, Default)]
struct Totals {
    low: usize,
    medium: usize,
    high: usize,
}

#[derive(Clone, Debug)]
struct AuditReport {
    files_scanned: usize,
    commands_scanned: usize,
    findings: Vec<RiskFinding>,
    totals: Totals,
}

#[derive(Clone, Debug, Default)]
struct Config {
    inputs: Vec<PathBuf>,
    markdown_out: Option<PathBuf>,
    json_out: Option<PathBuf>,
}

fn main() {
    match run() {
        Ok(()) => {}
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(1);
        }
    }
}

fn run() -> Result<(), String> {
    let config = parse_args(env::args().skip(1).collect())?;
    let history_files = collect_history_files(&config.inputs)?;
    let mut entries = Vec::new();

    for (path, shell) in &history_files {
        entries.extend(parse_history_file(path, *shell)?);
    }

    let report = analyze_entries(history_files.len(), entries);
    print_console_report(&report);

    if let Some(path) = &config.markdown_out {
        write_text(path, &build_markdown_report(&report))?;
    }
    if let Some(path) = &config.json_out {
        write_text(path, &build_json_report(&report))?;
    }

    Ok(())
}

fn parse_args(args: Vec<String>) -> Result<Config, String> {
    let mut config = Config::default();
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--help" | "-h" => {
                print_help();
                std::process::exit(0);
            }
            "--markdown-out" => {
                index += 1;
                let value = args.get(index).ok_or("--markdown-out requires a path.")?;
                config.markdown_out = Some(PathBuf::from(value));
            }
            "--json-out" => {
                index += 1;
                let value = args.get(index).ok_or("--json-out requires a path.")?;
                config.json_out = Some(PathBuf::from(value));
            }
            value if value.starts_with("--") => return Err(format!("Unknown flag: {value}")),
            value => config.inputs.push(PathBuf::from(value)),
        }
        index += 1;
    }

    if config.inputs.is_empty() {
        config.inputs.push(PathBuf::from("."));
    }
    Ok(config)
}

fn print_help() {
    println!("shell-history-risk-auditor");
    println!();
    println!("Usage:");
    println!("  cargo run -- <history-file-or-directory> [more paths] [--markdown-out report.md] [--json-out report.json]");
    println!();
    println!("Examples:");
    println!("  cargo run -- $HOME/.bash_history");
    println!("  cargo run -- C:\\Users\\name\\AppData\\Roaming\\Microsoft\\Windows\\PowerShell --markdown-out reports\\history.md");
}

fn collect_history_files(inputs: &[PathBuf]) -> Result<Vec<(PathBuf, ShellKind)>, String> {
    let mut files = Vec::new();
    for input in inputs {
        if !input.exists() {
            return Err(format!("Path does not exist: {}", input.display()));
        }
        if input.is_file() {
            let shell = detect_shell_kind(input);
            files.push((input.to_path_buf(), shell));
            continue;
        }
        walk_history_dir(input, &mut files)?;
    }

    files.sort_by(|left, right| left.0.cmp(&right.0));
    files.dedup_by(|left, right| left.0 == right.0);

    if files.is_empty() {
        return Err(
            "No recognizable shell history files were found in the provided path(s).".to_string(),
        );
    }

    Ok(files)
}

fn walk_history_dir(root: &Path, output: &mut Vec<(PathBuf, ShellKind)>) -> Result<(), String> {
    for entry in
        fs::read_dir(root).map_err(|error| format!("Could not read {}: {error}", root.display()))?
    {
        let entry = entry.map_err(|error| {
            format!(
                "Could not read directory entry in {}: {error}",
                root.display()
            )
        })?;
        let path = entry.path();
        if path.is_dir() {
            walk_history_dir(&path, output)?;
            continue;
        }
        let shell = detect_shell_kind(&path);
        if !matches!(shell, ShellKind::Unknown) {
            output.push((path, shell));
        }
    }
    Ok(())
}

fn detect_shell_kind(path: &Path) -> ShellKind {
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let full = path.to_string_lossy().to_ascii_lowercase();
    if file_name == "consolehost_history.txt" || full.contains("psreadline") {
        ShellKind::PowerShell
    } else if file_name == ".bash_history" {
        ShellKind::Bash
    } else if file_name == ".zsh_history" {
        ShellKind::Zsh
    } else if file_name == "fish_history" {
        ShellKind::Fish
    } else if file_name == "history.txt" && full.contains("nushell") {
        ShellKind::Nushell
    } else {
        ShellKind::Unknown
    }
}

fn parse_history_file(path: &Path, shell: ShellKind) -> Result<Vec<HistoryEntry>, String> {
    let text = fs::read_to_string(path)
        .map_err(|error| format!("Could not read {}: {error}", path.display()))?;
    Ok(match shell {
        ShellKind::Fish => parse_fish_history(path, &text),
        _ => parse_line_history(path, shell, &text),
    })
}

fn parse_line_history(path: &Path, shell: ShellKind, text: &str) -> Vec<HistoryEntry> {
    text.lines()
        .enumerate()
        .filter_map(|(index, line)| {
            let normalized = normalize_command(shell, line);
            if normalized.is_empty() {
                return None;
            }
            Some(HistoryEntry {
                source_path: path.to_path_buf(),
                shell,
                line_number: index + 1,
                command: normalized,
            })
        })
        .collect()
}

fn parse_fish_history(path: &Path, text: &str) -> Vec<HistoryEntry> {
    let mut entries = Vec::new();
    for (index, line) in text.lines().enumerate() {
        let trimmed = line.trim();
        if let Some(command) = trimmed.strip_prefix("- cmd: ") {
            let normalized = command.trim().to_string();
            if normalized.is_empty() {
                continue;
            }
            entries.push(HistoryEntry {
                source_path: path.to_path_buf(),
                shell: ShellKind::Fish,
                line_number: index + 1,
                command: normalized,
            });
        }
    }
    entries
}

fn normalize_command(shell: ShellKind, line: &str) -> String {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    if matches!(shell, ShellKind::Zsh) && trimmed.starts_with(':') {
        if let Some((_, command)) = trimmed.split_once(';') {
            return command.trim().to_string();
        }
    }
    trimmed.to_string()
}

fn analyze_entries(files_scanned: usize, entries: Vec<HistoryEntry>) -> AuditReport {
    let mut findings = Vec::new();
    let mut totals = Totals::default();

    for entry in &entries {
        for finding in detect_risks(entry) {
            match finding.level {
                RiskLevel::Low => totals.low += 1,
                RiskLevel::Medium => totals.medium += 1,
                RiskLevel::High => totals.high += 1,
            }
            findings.push(finding);
        }
    }

    findings.sort_by(|left, right| {
        right
            .level
            .cmp(&left.level)
            .then_with(|| left.source_path.cmp(&right.source_path))
            .then_with(|| left.line_number.cmp(&right.line_number))
    });

    AuditReport {
        files_scanned,
        commands_scanned: entries.len(),
        findings,
        totals,
    }
}

fn detect_risks(entry: &HistoryEntry) -> Vec<RiskFinding> {
    let command = entry.command.trim();
    let lower = command.to_ascii_lowercase();
    let mut findings = Vec::new();

    let add = |findings: &mut Vec<RiskFinding>, level: RiskLevel, label: &str, reason: &str| {
        findings.push(RiskFinding {
            level,
            label: label.to_string(),
            reason: reason.to_string(),
            command: truncate_command(command),
            source_path: entry.source_path.clone(),
            shell: entry.shell,
            line_number: entry.line_number,
        });
    };

    if lower.contains("rm -rf")
        || lower.contains("rd /s /q")
        || lower.contains("del /f /s /q")
        || lower.starts_with("format ")
        || lower.contains("diskpart")
    {
        add(
            &mut findings,
            RiskLevel::High,
            "destructive command",
            "Command history contains a destructive filesystem or disk operation.",
        );
    }

    if lower.contains("git reset --hard")
        || lower.contains("git push --force")
        || lower.contains("git push -f")
    {
        add(
            &mut findings,
            RiskLevel::Medium,
            "history-rewriting git command",
            "Command rewrites git history or force-pushes a branch.",
        );
    }

    if (lower.contains("curl ")
        || lower.contains("wget ")
        || lower.contains("irm ")
        || lower.contains("invoke-webrequest "))
        && (lower.contains("| sh")
            || lower.contains("| bash")
            || lower.contains("| iex")
            || lower.contains("invoke-expression"))
    {
        add(
            &mut findings,
            RiskLevel::High,
            "remote script execution",
            "Downloads are being piped straight into a shell or expression evaluator.",
        );
    }

    if lower.contains("clear-history")
        || lower.contains("history -c")
        || lower.contains("history -w")
        || lower.contains("remove-item")
            && (lower.contains("historysavepath") || lower.contains("psreadline"))
    {
        add(
            &mut findings,
            RiskLevel::Medium,
            "history tampering",
            "Command appears to clear or overwrite shell history.",
        );
    }

    if lower.contains("password=")
        || lower.contains("token=")
        || lower.contains("authorization: bearer")
        || lower.contains("aws_secret_access_key")
        || command.contains("ghp_")
        || command.contains("github_pat_")
        || command.contains("AKIA")
        || command.contains("sk-")
    {
        add(&mut findings, RiskLevel::High, "secret-like token", "Command contains a token- or credential-like value that should not live in shell history.");
    }

    if lower.contains("sshpass")
        || lower.contains("mysql -p")
        || lower.contains("psql postgresql://")
    {
        add(
            &mut findings,
            RiskLevel::Medium,
            "inline credential usage",
            "Command appears to include a password-bearing helper or connection string.",
        );
    }

    if lower.contains("set-executionpolicy bypass") || lower.contains("chmod 777") {
        add(
            &mut findings,
            RiskLevel::Low,
            "safety bypass",
            "Command weakens an execution or file-permission safety boundary.",
        );
    }

    findings
}

fn truncate_command(command: &str) -> String {
    const LIMIT: usize = 140;
    if command.chars().count() <= LIMIT {
        return command.to_string();
    }
    let mut shortened = command.chars().take(LIMIT - 1).collect::<String>();
    shortened.push('…');
    shortened
}

fn print_console_report(report: &AuditReport) {
    println!("Shell History Risk Auditor");
    println!("Files scanned: {}", report.files_scanned);
    println!("Commands scanned: {}", report.commands_scanned);
    println!(
        "Findings: high {} | medium {} | low {}",
        report.totals.high, report.totals.medium, report.totals.low
    );
    println!();

    if report.findings.is_empty() {
        println!("No risky command patterns were detected in the scanned history files.");
        return;
    }

    println!("Top findings");
    for finding in report.findings.iter().take(12) {
        println!(
            "- [{}] {} | {}:{} | {}",
            finding.level.label(),
            finding.label,
            finding.source_path.display(),
            finding.line_number,
            finding.command
        );
    }
}

fn build_markdown_report(report: &AuditReport) -> String {
    let mut lines = vec![
        "# Shell History Risk Audit".to_string(),
        String::new(),
        format!("- Files scanned: {}", report.files_scanned),
        format!("- Commands scanned: {}", report.commands_scanned),
        format!("- High findings: {}", report.totals.high),
        format!("- Medium findings: {}", report.totals.medium),
        format!("- Low findings: {}", report.totals.low),
        String::new(),
        "## Findings".to_string(),
        String::new(),
    ];

    if report.findings.is_empty() {
        lines.push("- No risky command patterns were detected.".to_string());
    } else {
        for finding in &report.findings {
            lines.push(format!(
                "- `{}` {} at `{}`:{}: {}",
                finding.level.label(),
                finding.label,
                finding.source_path.display(),
                finding.line_number,
                finding.reason
            ));
            lines.push(format!("  Shell: `{}`", finding.shell.label()));
            lines.push(format!(
                "  Command: `{}`",
                escape_markdown_ticks(&finding.command)
            ));
        }
    }

    lines.join("\n")
}

fn build_json_report(report: &AuditReport) -> String {
    let mut lines = vec![
        "{".to_string(),
        format!("  \"files_scanned\": {},", report.files_scanned),
        format!("  \"commands_scanned\": {},", report.commands_scanned),
        "  \"totals\": {".to_string(),
        format!("    \"high\": {},", report.totals.high),
        format!("    \"medium\": {},", report.totals.medium),
        format!("    \"low\": {}", report.totals.low),
        "  },".to_string(),
        "  \"findings\": [".to_string(),
    ];

    for (index, finding) in report.findings.iter().enumerate() {
        let suffix = if index + 1 == report.findings.len() {
            ""
        } else {
            ","
        };
        lines.push("    {".to_string());
        lines.push(format!("      \"level\": \"{}\",", finding.level.label()));
        lines.push(format!(
            "      \"label\": \"{}\",",
            escape_json(&finding.label)
        ));
        lines.push(format!(
            "      \"reason\": \"{}\",",
            escape_json(&finding.reason)
        ));
        lines.push(format!(
            "      \"command\": \"{}\",",
            escape_json(&finding.command)
        ));
        lines.push(format!(
            "      \"source_path\": \"{}\",",
            escape_json(&finding.source_path.display().to_string())
        ));
        lines.push(format!("      \"shell\": \"{}\",", finding.shell.label()));
        lines.push(format!("      \"line_number\": {}", finding.line_number));
        lines.push(format!("    }}{suffix}"));
    }

    lines.push("  ]".to_string());
    lines.push("}".to_string());
    lines.join("\n")
}

fn write_text(path: &Path, text: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Could not create {}: {error}", parent.display()))?;
    }
    fs::write(path, text).map_err(|error| format!("Could not write {}: {error}", path.display()))
}

fn escape_json(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('\"', "\\\"")
        .replace('\n', "\\n")
}

fn escape_markdown_ticks(value: &str) -> String {
    value.replace('`', "'")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_zsh_extended_history_prefix() {
        let normalized = normalize_command(
            ShellKind::Zsh,
            ": 1710000000:0;git push --force origin main",
        );
        assert_eq!(normalized, "git push --force origin main");
    }

    #[test]
    fn detects_secret_like_command() {
        let entry = HistoryEntry {
            source_path: PathBuf::from(".bash_history"),
            shell: ShellKind::Bash,
            line_number: 4,
            command: "curl https://api.example.dev -H \"Authorization: Bearer sk-abc123\""
                .to_string(),
        };
        let findings = detect_risks(&entry);
        assert!(findings
            .iter()
            .any(|finding| finding.label == "secret-like token"));
        assert!(
            findings
                .iter()
                .any(|finding| finding.label == "remote script execution")
                == false
        );
    }

    #[test]
    fn detects_remote_script_execution() {
        let entry = HistoryEntry {
            source_path: PathBuf::from("ConsoleHost_history.txt"),
            shell: ShellKind::PowerShell,
            line_number: 9,
            command: "irm https://example.com/install.ps1 | iex".to_string(),
        };
        let findings = detect_risks(&entry);
        assert!(findings
            .iter()
            .any(|finding| finding.label == "remote script execution"));
    }
}
