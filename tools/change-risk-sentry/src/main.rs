use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Clone, Debug, Default)]
struct FileChange {
    path: String,
    staged_status: Option<char>,
    unstaged_status: Option<char>,
    staged_added: usize,
    staged_deleted: usize,
    unstaged_added: usize,
    unstaged_deleted: usize,
    untracked: bool,
    binary: bool,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum Category {
    Source,
    Tests,
    Docs,
    Config,
    Assets,
    Lockfile,
    Manifest,
    Unknown,
}

impl Category {
    fn label(self) -> &'static str {
        match self {
            Category::Source => "source",
            Category::Tests => "tests",
            Category::Docs => "docs",
            Category::Config => "config",
            Category::Assets => "assets",
            Category::Lockfile => "lockfiles",
            Category::Manifest => "manifests",
            Category::Unknown => "other",
        }
    }
}

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

#[derive(Clone, Debug, Default)]
struct CategoryTotals {
    files: usize,
    added: usize,
    deleted: usize,
}

#[derive(Clone, Debug, Default)]
struct DirectoryTotals {
    files: usize,
    added: usize,
    deleted: usize,
}

#[derive(Clone, Debug)]
struct Analysis {
    repo_root: String,
    branch: String,
    mode_label: String,
    changes: Vec<FileChange>,
    totals: BTreeMap<Category, CategoryTotals>,
    directories: BTreeMap<String, DirectoryTotals>,
    risk_flags: Vec<String>,
    headline: String,
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
    let args = env::args().skip(1).collect::<Vec<_>>();
    let mut repo_arg: Option<String> = None;
    let mut base_ref: Option<String> = None;
    let mut json_out: Option<PathBuf> = None;
    let mut md_out: Option<PathBuf> = None;
    let mut fail_on: Option<RiskLevel> = None;

    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--help" | "-h" => {
                print_help();
                return Ok(());
            }
            "--json-out" => {
                index += 1;
                let value = args.get(index).ok_or("--json-out requires a path.")?;
                json_out = Some(PathBuf::from(value));
            }
            "--base" => {
                index += 1;
                let value = args.get(index).ok_or("--base requires a git ref.")?;
                base_ref = Some(value.to_string());
            }
            "--md-out" => {
                index += 1;
                let value = args.get(index).ok_or("--md-out requires a path.")?;
                md_out = Some(PathBuf::from(value));
            }
            "--fail-on" => {
                index += 1;
                let value = args
                    .get(index)
                    .ok_or("--fail-on requires low, medium, or high.")?;
                fail_on = Some(parse_risk_level(value)?);
            }
            value if value.starts_with("--") => return Err(format!("Unknown flag: {value}")),
            value => {
                if repo_arg.is_some() {
                    return Err("Only one repo path can be provided.".to_string());
                }
                repo_arg = Some(value.to_string());
            }
        }
        index += 1;
    }

    let repo = PathBuf::from(repo_arg.unwrap_or_else(|| ".".to_string()));
    let analysis = analyze_repo(&repo, base_ref.as_deref())?;
    print_console_report(&analysis);

    if let Some(path) = json_out {
        write_json_report(&analysis, &path)?;
    }
    if let Some(path) = md_out {
        write_markdown_report(&analysis, &path)?;
    }
    if let Some(threshold) = fail_on {
        let observed = highest_risk_level(&analysis.risk_flags);
        if observed >= Some(threshold) {
            return Err(format!(
                "Risk threshold `{}` met: highest observed level was `{}`.",
                threshold.label(),
                observed
                    .expect("observed risk level must exist when threshold matched")
                    .label()
            ));
        }
    }

    Ok(())
}

fn parse_risk_level(value: &str) -> Result<RiskLevel, String> {
    match value.trim().to_ascii_lowercase().as_str() {
        "low" => Ok(RiskLevel::Low),
        "medium" => Ok(RiskLevel::Medium),
        "high" => Ok(RiskLevel::High),
        _ => Err(format!(
            "Unknown risk level `{value}`. Use low, medium, or high."
        )),
    }
}

fn print_help() {
    println!("change-risk-sentry");
    println!();
    println!("Usage:");
    println!(
        "  change-risk-sentry [repo_path] [--base origin/main] [--json-out report.json] [--md-out report.md] [--fail-on medium]"
    );
    println!();
    println!("Examples:");
    println!("  change-risk-sentry .");
    println!("  change-risk-sentry . --base origin/main");
    println!("  change-risk-sentry C:\\repo --md-out risk-report.md");
    println!("  change-risk-sentry . --fail-on high");
}

fn analyze_repo(repo: &Path, base_ref: Option<&str>) -> Result<Analysis, String> {
    let repo_root = git_output(repo, &["rev-parse", "--show-toplevel"])?;
    let branch = git_output(repo, &["symbolic-ref", "--short", "HEAD"])
        .unwrap_or_else(|_| "HEAD".to_string());
    let local_status = git_output(repo, &["status", "--short", "--untracked-files=all"])?;
    let (mode_label, changes) = if let Some(base_ref) = base_ref {
        let merge_base = git_output(repo, &["merge-base", base_ref, "HEAD"])?;
        let name_status = git_output(repo, &["diff", "--name-status", &merge_base, "HEAD"])?;
        let range_numstat = git_output(repo, &["diff", "--numstat", &merge_base, "HEAD"])?;
        let mut changes = parse_name_status(&name_status);
        apply_numstat(&mut changes, &range_numstat, true);
        (format!("Branch delta vs {base_ref}"), changes)
    } else {
        let staged_numstat = git_output(repo, &["diff", "--cached", "--numstat"])?;
        let unstaged_numstat = git_output(repo, &["diff", "--numstat"])?;
        let mut changes = parse_status(&local_status);
        apply_numstat(&mut changes, &staged_numstat, true);
        apply_numstat(&mut changes, &unstaged_numstat, false);
        ("Worktree risk review".to_string(), changes)
    };

    let mut totals: BTreeMap<Category, CategoryTotals> = BTreeMap::new();
    let mut directories: BTreeMap<String, DirectoryTotals> = BTreeMap::new();
    for change in &changes {
        let category = categorize(&change.path);
        let entry = totals.entry(category).or_default();
        entry.files += 1;
        entry.added += change.staged_added + change.unstaged_added;
        entry.deleted += change.staged_deleted + change.unstaged_deleted;

        let directory = top_level_directory(&change.path);
        let directory_entry = directories.entry(directory).or_default();
        directory_entry.files += 1;
        directory_entry.added += change.staged_added + change.unstaged_added;
        directory_entry.deleted += change.staged_deleted + change.unstaged_deleted;
    }

    let risk_flags = build_risk_flags(&changes, &totals, &directories, base_ref, &local_status);
    let headline = if changes.is_empty() {
        "Clean worktree".to_string()
    } else if risk_flags.iter().any(|flag| flag.starts_with("High:")) {
        "High review attention recommended".to_string()
    } else if risk_flags.iter().any(|flag| flag.starts_with("Medium:")) {
        "Moderate review attention recommended".to_string()
    } else {
        "Low review attention recommended".to_string()
    };

    Ok(Analysis {
        repo_root,
        branch,
        mode_label,
        changes,
        totals,
        directories,
        risk_flags,
        headline,
    })
}

fn parse_status(status: &str) -> Vec<FileChange> {
    let mut changes = Vec::new();
    for raw_line in status.lines() {
        if raw_line.trim().is_empty() {
            continue;
        }

        let code = raw_line.chars().take(2).collect::<Vec<_>>();
        let path_part = raw_line.chars().skip(3).collect::<String>();
        let path_part = path_part.trim();
        let path = if let Some((_, renamed)) = path_part.split_once("->") {
            renamed.trim().to_string()
        } else {
            path_part.to_string()
        };

        let untracked = code.first() == Some(&'?') && code.get(1) == Some(&'?');
        changes.push(FileChange {
            path,
            staged_status: code
                .first()
                .copied()
                .filter(|value| *value != ' ' && *value != '?'),
            unstaged_status: code
                .get(1)
                .copied()
                .filter(|value| *value != ' ' && *value != '?'),
            untracked,
            ..Default::default()
        });
    }
    changes
}

fn parse_name_status(status: &str) -> Vec<FileChange> {
    let mut changes = Vec::new();
    for raw_line in status.lines() {
        if raw_line.trim().is_empty() {
            continue;
        }

        let parts = raw_line.split('\t').collect::<Vec<_>>();
        if parts.len() < 2 {
            continue;
        }

        let code = parts[0];
        let path = if code.starts_with('R') || code.starts_with('C') {
            parts.last().unwrap_or(&"").trim().to_string()
        } else {
            parts[1].trim().to_string()
        };

        changes.push(FileChange {
            path,
            staged_status: code.chars().next(),
            ..Default::default()
        });
    }
    changes
}

fn apply_numstat(changes: &mut Vec<FileChange>, numstat: &str, staged: bool) {
    for line in numstat.lines() {
        let parts = line.split('\t').collect::<Vec<_>>();
        if parts.len() < 3 {
            continue;
        }

        let path = normalize_diff_path(parts[2]);
        let added_raw = parts[0];
        let deleted_raw = parts[1];
        let binary = added_raw == "-" || deleted_raw == "-";
        let added = if binary {
            0
        } else {
            added_raw.parse::<usize>().unwrap_or(0)
        };
        let deleted = if binary {
            0
        } else {
            deleted_raw.parse::<usize>().unwrap_or(0)
        };

        let change = if let Some(existing) = changes.iter_mut().find(|change| change.path == path) {
            existing
        } else {
            changes.push(FileChange {
                path: path.clone(),
                ..Default::default()
            });
            changes.last_mut().expect("last_mut after push must exist")
        };

        if staged {
            change.staged_added = added;
            change.staged_deleted = deleted;
        } else {
            change.unstaged_added = added;
            change.unstaged_deleted = deleted;
        }
        if binary {
            change.binary = true;
        }
    }
}

fn normalize_diff_path(raw: &str) -> String {
    if let Some((_, renamed)) = raw.split_once("=>") {
        return renamed.replace('}', "").trim().to_string();
    }
    raw.trim().to_string()
}

fn categorize(path: &str) -> Category {
    let lower = path.to_ascii_lowercase();
    if lower.ends_with(".lock")
        || lower.ends_with("package-lock.json")
        || lower.ends_with("cargo.lock")
        || lower.ends_with("poetry.lock")
    {
        return Category::Lockfile;
    }
    if lower.ends_with("package.json")
        || lower.ends_with("cargo.toml")
        || lower.ends_with("requirements.txt")
        || lower.ends_with("pyproject.toml")
        || lower.ends_with("composer.json")
    {
        return Category::Manifest;
    }
    if lower.contains("test") || lower.contains("spec") {
        return Category::Tests;
    }
    if lower.ends_with(".md") || lower.ends_with(".rst") || lower.ends_with(".txt") {
        return Category::Docs;
    }
    if lower.ends_with(".yml")
        || lower.ends_with(".yaml")
        || lower.ends_with(".toml")
        || lower.ends_with(".ini")
        || lower.ends_with(".env")
        || lower.contains(".github/")
        || lower.contains("dockerfile")
    {
        return Category::Config;
    }
    if lower.ends_with(".png")
        || lower.ends_with(".jpg")
        || lower.ends_with(".jpeg")
        || lower.ends_with(".gif")
        || lower.ends_with(".svg")
        || lower.ends_with(".ico")
    {
        return Category::Assets;
    }
    if lower.ends_with(".rs")
        || lower.ends_with(".py")
        || lower.ends_with(".js")
        || lower.ends_with(".jsx")
        || lower.ends_with(".ts")
        || lower.ends_with(".tsx")
        || lower.ends_with(".cpp")
        || lower.ends_with(".c")
        || lower.ends_with(".h")
        || lower.ends_with(".hpp")
        || lower.ends_with(".java")
        || lower.ends_with(".cs")
        || lower.ends_with(".php")
        || lower.ends_with(".html")
        || lower.ends_with(".css")
    {
        return Category::Source;
    }
    Category::Unknown
}

fn top_level_directory(path: &str) -> String {
    let normalized = path.replace('\\', "/");
    normalized
        .split('/')
        .find(|segment| !segment.trim().is_empty())
        .unwrap_or("(root)")
        .to_string()
}

fn build_risk_flags(
    changes: &[FileChange],
    totals: &BTreeMap<Category, CategoryTotals>,
    directories: &BTreeMap<String, DirectoryTotals>,
    base_ref: Option<&str>,
    local_status: &str,
) -> Vec<String> {
    let mut flags = Vec::new();
    let source_files = totals
        .get(&Category::Source)
        .map(|total| total.files)
        .unwrap_or(0);
    let test_files = totals
        .get(&Category::Tests)
        .map(|total| total.files)
        .unwrap_or(0);
    let config_files = totals
        .get(&Category::Config)
        .map(|total| total.files)
        .unwrap_or(0);
    let manifest_files = totals
        .get(&Category::Manifest)
        .map(|total| total.files)
        .unwrap_or(0);
    let lock_files = totals
        .get(&Category::Lockfile)
        .map(|total| total.files)
        .unwrap_or(0);
    let docs_only = !changes.is_empty()
        && changes
            .iter()
            .all(|change| categorize(&change.path) == Category::Docs);
    let total_deleted = changes
        .iter()
        .map(|change| change.staged_deleted + change.unstaged_deleted)
        .sum::<usize>();
    let binary_files = changes.iter().filter(|change| change.binary).count();
    let untracked = changes.iter().filter(|change| change.untracked).count();
    let local_pending = local_status
        .lines()
        .filter(|line| !line.trim().is_empty())
        .count();
    let mixed_state = changes
        .iter()
        .filter(|change| change.staged_status.is_some() && change.unstaged_status.is_some())
        .count();
    let directory_count = directories.len();

    if source_files > 0 && test_files == 0 {
        flags.push(
            "Medium: source files changed without any test files in the same worktree.".to_string(),
        );
    }
    if mixed_state > 0 {
        flags.push(format!(
            "Medium: {} file(s) have both staged and unstaged edits, which increases commit-prep risk.",
            mixed_state
        ));
    }
    if config_files > 0 {
        flags.push("Medium: configuration or deployment-facing files changed.".to_string());
    }
    if directory_count >= 4 {
        flags.push(format!(
            "Medium: change surface spans {} top-level directories, so review context is spread broadly.",
            directory_count
        ));
    }
    if lock_files > 0 && manifest_files == 0 {
        flags.push("Medium: lockfiles changed without a paired manifest edit.".to_string());
    }
    if total_deleted >= 200 {
        flags.push(format!(
            "High: {} lines deleted across the current worktree; review for accidental removals.",
            total_deleted
        ));
    }
    if binary_files > 0 {
        flags.push(format!(
            "Medium: {} binary-looking file(s) changed, so diff review may be incomplete from text output alone.",
            binary_files
        ));
    }
    if untracked > 0 {
        flags.push(format!(
            "Low: {} untracked file(s) are present and can be missed during commit preparation.",
            untracked
        ));
    }
    if let Some(base_ref) = base_ref {
        flags.push(format!(
            "Low: base mode is reading committed branch delta versus {base_ref}; local-only edits are not part of the churn totals."
        ));
        if local_pending > 0 {
            flags.push(format!(
                "Low: {} local worktree file(s) are also pending outside the base-diff snapshot.",
                local_pending
            ));
        }
    }
    if docs_only {
        flags.push("Low: only documentation files changed in the current worktree.".to_string());
    }
    if flags.is_empty() && !changes.is_empty() {
        flags.push(
            "Low: change surface is compact and balanced across code, tests, and metadata."
                .to_string(),
        );
    }
    if changes.is_empty() {
        flags.push("Low: git status is clean.".to_string());
    }
    flags
}

fn highest_risk_level(flags: &[String]) -> Option<RiskLevel> {
    flags
        .iter()
        .filter_map(|flag| {
            if flag.starts_with("High:") {
                Some(RiskLevel::High)
            } else if flag.starts_with("Medium:") {
                Some(RiskLevel::Medium)
            } else if flag.starts_with("Low:") {
                Some(RiskLevel::Low)
            } else {
                None
            }
        })
        .max()
}

fn print_console_report(analysis: &Analysis) {
    println!("Change Risk Sentry");
    println!("Repo: {}", analysis.repo_root);
    println!("Branch: {}", analysis.branch);
    println!("Mode: {}", analysis.mode_label);
    println!("Headline: {}", analysis.headline);
    println!("Files touched: {}", analysis.changes.len());
    println!();

    println!("Category breakdown");
    for (category, totals) in &analysis.totals {
        println!(
            "- {:<10} files {:>2} | +{:>4} / -{:>4}",
            category.label(),
            totals.files,
            totals.added,
            totals.deleted
        );
    }
    if analysis.totals.is_empty() {
        println!("- clean");
    }

    println!();
    println!("Top churn files");
    let mut by_churn = analysis.changes.clone();
    by_churn.sort_by_key(|change| {
        std::cmp::Reverse(
            change.staged_added
                + change.staged_deleted
                + change.unstaged_added
                + change.unstaged_deleted,
        )
    });
    for change in by_churn.into_iter().take(5) {
        let churn = change.staged_added
            + change.staged_deleted
            + change.unstaged_added
            + change.unstaged_deleted;
        let staged = change.staged_status.unwrap_or('-');
        let unstaged = change.unstaged_status.unwrap_or('-');
        println!(
            "- [{}{}] {} | churn {}{}",
            staged,
            unstaged,
            change.path,
            churn,
            if change.untracked { " | untracked" } else { "" }
        );
    }
    if analysis.changes.is_empty() {
        println!("- no pending changes");
    }

    println!();
    println!("Risk flags");
    for flag in &analysis.risk_flags {
        println!("- {flag}");
    }

    println!();
    println!("Top directories");
    let mut directories = analysis.directories.iter().collect::<Vec<_>>();
    directories.sort_by_key(|(_, totals)| std::cmp::Reverse(totals.added + totals.deleted));
    for (directory, totals) in directories.into_iter().take(5) {
        println!(
            "- {} | files {} | +{} / -{}",
            directory, totals.files, totals.added, totals.deleted
        );
    }
}

fn write_json_report(analysis: &Analysis, path: &Path) -> Result<(), String> {
    let mut content = String::new();
    content.push_str("{\n");
    content.push_str(&format!(
        "  \"repo_root\": \"{}\",\n",
        escape_json(&analysis.repo_root)
    ));
    content.push_str(&format!(
        "  \"branch\": \"{}\",\n",
        escape_json(&analysis.branch)
    ));
    content.push_str(&format!(
        "  \"mode\": \"{}\",\n",
        escape_json(&analysis.mode_label)
    ));
    content.push_str(&format!(
        "  \"headline\": \"{}\",\n",
        escape_json(&analysis.headline)
    ));
    content.push_str("  \"risk_flags\": [\n");
    for (index, flag) in analysis.risk_flags.iter().enumerate() {
        let suffix = if index + 1 == analysis.risk_flags.len() {
            ""
        } else {
            ","
        };
        content.push_str(&format!("    \"{}\"{}\n", escape_json(flag), suffix));
    }
    content.push_str("  ],\n");
    content.push_str("  \"changes\": [\n");
    for (index, change) in analysis.changes.iter().enumerate() {
        let suffix = if index + 1 == analysis.changes.len() {
            ""
        } else {
            ","
        };
        content.push_str("    {\n");
        content.push_str(&format!(
            "      \"path\": \"{}\",\n",
            escape_json(&change.path)
        ));
        content.push_str(&format!(
            "      \"category\": \"{}\",\n",
            categorize(&change.path).label()
        ));
        content.push_str(&format!(
            "      \"added\": {},\n",
            change.staged_added + change.unstaged_added
        ));
        content.push_str(&format!(
            "      \"deleted\": {},\n",
            change.staged_deleted + change.unstaged_deleted
        ));
        content.push_str(&format!("      \"untracked\": {}\n", change.untracked));
        content.push_str(&format!("    }}{}\n", suffix));
    }
    content.push_str("  ],\n");
    content.push_str("  \"directories\": [\n");
    let directories = analysis.directories.iter().collect::<Vec<_>>();
    for (index, (directory, totals)) in directories.iter().enumerate() {
        let suffix = if index + 1 == directories.len() {
            ""
        } else {
            ","
        };
        content.push_str("    {\n");
        content.push_str(&format!(
            "      \"name\": \"{}\",\n",
            escape_json(directory)
        ));
        content.push_str(&format!("      \"files\": {},\n", totals.files));
        content.push_str(&format!("      \"added\": {},\n", totals.added));
        content.push_str(&format!("      \"deleted\": {}\n", totals.deleted));
        content.push_str(&format!("    }}{}\n", suffix));
    }
    content.push_str("  ]\n");
    content.push_str("}\n");
    write_text(path, &content)
}

fn write_markdown_report(analysis: &Analysis, path: &Path) -> Result<(), String> {
    let mut content = String::new();
    content.push_str("# Change Risk Sentry Report\n\n");
    content.push_str(&format!("- Repo: `{}`\n", analysis.repo_root));
    content.push_str(&format!("- Branch: `{}`\n", analysis.branch));
    content.push_str(&format!("- Mode: {}\n", analysis.mode_label));
    content.push_str(&format!("- Headline: {}\n", analysis.headline));
    content.push_str(&format!("- Files touched: {}\n\n", analysis.changes.len()));
    content.push_str("## Category Breakdown\n\n");
    if analysis.totals.is_empty() {
        content.push_str("- Clean worktree\n");
    } else {
        for (category, totals) in &analysis.totals {
            content.push_str(&format!(
                "- `{}`: {} file(s), +{}, -{}\n",
                category.label(),
                totals.files,
                totals.added,
                totals.deleted
            ));
        }
    }
    content.push_str("\n## Risk Flags\n\n");
    for flag in &analysis.risk_flags {
        content.push_str(&format!("- {}\n", flag));
    }
    content.push_str("\n## Top Directories\n\n");
    let mut directories = analysis.directories.iter().collect::<Vec<_>>();
    directories.sort_by_key(|(_, totals)| std::cmp::Reverse(totals.added + totals.deleted));
    for (directory, totals) in directories.into_iter().take(8) {
        content.push_str(&format!(
            "- `{}`: {} file(s), +{}, -{}\n",
            directory, totals.files, totals.added, totals.deleted
        ));
    }
    content.push_str("\n## Top Churn Files\n\n");
    let mut by_churn = analysis.changes.clone();
    by_churn.sort_by_key(|change| {
        std::cmp::Reverse(
            change.staged_added
                + change.staged_deleted
                + change.unstaged_added
                + change.unstaged_deleted,
        )
    });
    for change in by_churn.into_iter().take(8) {
        let churn = change.staged_added
            + change.staged_deleted
            + change.unstaged_added
            + change.unstaged_deleted;
        content.push_str(&format!(
            "- `{}` ({}) churn {}\n",
            change.path,
            categorize(&change.path).label(),
            churn
        ));
    }
    write_text(path, &content)
}

fn write_text(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Could not create {}: {error}", parent.display()))?;
    }
    fs::write(path, content).map_err(|error| format!("Could not write {}: {error}", path.display()))
}

fn git_output(repo: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new("git")
        .args(args)
        .current_dir(repo)
        .output()
        .map_err(|error| format!("Failed to run git {:?}: {error}", args))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn escape_json(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('\"', "\\\"")
        .replace('\n', "\\n")
}
