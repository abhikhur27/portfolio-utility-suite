use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::PathBuf;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
enum Category {
    Grading,
    Exams,
    Attendance,
    LateWork,
    Schedule,
    Materials,
    Contact,
    General,
}

impl Category {
    fn label(self) -> &'static str {
        match self {
            Category::Grading => "grading",
            Category::Exams => "exams",
            Category::Attendance => "attendance",
            Category::LateWork => "late work",
            Category::Schedule => "schedule",
            Category::Materials => "materials",
            Category::Contact => "contact",
            Category::General => "general",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct LineEntry {
    normalized: String,
    original: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Change {
    category: Category,
    severity: u8,
    original: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct DiffReport {
    added: Vec<Change>,
    removed: Vec<Change>,
    modified: Vec<ModifiedChange>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct OutputTargets {
    markdown: Option<PathBuf>,
    json: Option<PathBuf>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ModifiedChange {
    category: Category,
    severity: u8,
    before: String,
    after: String,
    similarity: u16,
}

fn main() {
    match run() {
        Ok(RunOutcome::Rendered(output)) => println!("{output}"),
        Ok(RunOutcome::Help(output)) => println!("{output}"),
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(1);
        }
    }
}

enum RunOutcome {
    Rendered(String),
    Help(String),
}

fn run() -> Result<RunOutcome, String> {
    let (before_path, after_path, outputs) = match parse_args(env::args().skip(1)) {
        Ok(values) => values,
        Err(message) if message == "__HELP__" => return Ok(RunOutcome::Help(usage())),
        Err(message) => return Err(message),
    };
    let before = fs::read_to_string(&before_path)
        .map_err(|error| format!("Could not read {}: {error}", before_path.display()))?;
    let after = fs::read_to_string(&after_path)
        .map_err(|error| format!("Could not read {}: {error}", after_path.display()))?;

    let report = diff_texts(&before, &after);
    let rendered = render_markdown(&before_path, &after_path, &report);

    if let Some(markdown_path) = outputs.markdown {
        fs::write(&markdown_path, &rendered)
            .map_err(|error| format!("Could not write {}: {error}", markdown_path.display()))?;
    }

    if let Some(json_path) = outputs.json {
        fs::write(&json_path, render_json(&before_path, &after_path, &report))
            .map_err(|error| format!("Could not write {}: {error}", json_path.display()))?;
    }

    Ok(RunOutcome::Rendered(rendered))
}

fn parse_args<I>(args: I) -> Result<(PathBuf, PathBuf, OutputTargets), String>
where
    I: IntoIterator<Item = String>,
{
    let mut positionals = Vec::new();
    let mut outputs = OutputTargets::default();
    let mut iter = args.into_iter();

    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--help" | "-h" => return Err(String::from("__HELP__")),
            "--markdown" => {
                let path = iter.next().ok_or_else(usage)?;
                outputs.markdown = Some(PathBuf::from(path));
            }
            "--json" => {
                let path = iter.next().ok_or_else(usage)?;
                outputs.json = Some(PathBuf::from(path));
            }
            _ if arg.starts_with("--") => return Err(format!("Unknown flag: {arg}\n\n{}", usage())),
            _ => positionals.push(PathBuf::from(arg)),
        }
    }

    if positionals.len() != 2 {
        return Err(usage());
    }

    Ok((positionals.remove(0), positionals.remove(0), outputs))
}

fn usage() -> String {
    [
        "Usage: syllabus-diff-brief <before.txt> <after.txt> [--markdown report.md] [--json report.json]",
        "",
        "Compares two syllabus text or markdown exports and summarizes policy changes.",
    ]
    .join("\n")
}

fn diff_texts(before: &str, after: &str) -> DiffReport {
    let before_map: BTreeMap<String, String> = extract_lines(before)
        .into_iter()
        .map(|entry| (entry.normalized, entry.original))
        .collect();
    let after_map: BTreeMap<String, String> = extract_lines(after)
        .into_iter()
        .map(|entry| (entry.normalized, entry.original))
        .collect();

    let mut added = Vec::new();
    let mut removed = Vec::new();

    for (normalized, original) in &after_map {
        if !before_map.contains_key(normalized) {
            added.push(build_change(original));
        }
    }

    for (normalized, original) in &before_map {
        if !after_map.contains_key(normalized) {
            removed.push(build_change(original));
        }
    }

    let modified = match_modified_changes(&mut added, &mut removed);
    sort_changes(&mut added);
    sort_changes(&mut removed);
    DiffReport {
        added,
        removed,
        modified,
    }
}

fn extract_lines(input: &str) -> Vec<LineEntry> {
    input
        .lines()
        .filter_map(|line| {
            let collapsed = line.split_whitespace().collect::<Vec<_>>().join(" ");
            let normalized = collapsed
                .trim_matches(|character: char| matches!(character, '-' | '*' | '#' | '>' | '`' | ' '))
                .trim()
                .to_lowercase();
            if normalized.is_empty() {
                None
            } else {
                Some(LineEntry {
                    normalized,
                    original: collapsed.trim().to_string(),
                })
            }
        })
        .collect()
}

fn build_change(original: &str) -> Change {
    let lowercase = original.to_lowercase();
    let category = classify_category(&lowercase);
    let severity = classify_severity(&lowercase, category);
    Change {
        category,
        severity,
        original: original.to_string(),
    }
}

fn classify_category(line: &str) -> Category {
    if contains_any(line, &["grade", "grading", "%", "weighted", "points", "rubric"]) {
        Category::Grading
    } else if contains_any(line, &["exam", "midterm", "final", "quiz", "test"]) {
        Category::Exams
    } else if contains_any(line, &["attendance", "absence", "participation"]) {
        Category::Attendance
    } else if contains_any(line, &["late", "extension", "penalty", "make-up", "makeup"]) {
        Category::LateWork
    } else if contains_any(
        line,
        &[
            "week",
            "date",
            "deadline",
            "due",
            "schedule",
            "calendar",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
        ],
    ) {
        Category::Schedule
    } else if contains_any(line, &["textbook", "material", "software", "required", "supplies"]) {
        Category::Materials
    } else if contains_any(line, &["office hours", "email", "contact", "instructor", "ta"]) {
        Category::Contact
    } else {
        Category::General
    }
}

fn classify_severity(line: &str, category: Category) -> u8 {
    if has_date_signal(line) || matches!(category, Category::Grading | Category::Exams | Category::LateWork) {
        3
    } else if matches!(category, Category::Attendance | Category::Schedule | Category::Materials) {
        2
    } else {
        1
    }
}

fn has_date_signal(line: &str) -> bool {
    let months = [
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    ];
    if months.iter().any(|month| line.contains(month)) {
        return true;
    }

    let bytes = line.as_bytes();
    bytes.windows(5).any(|window| {
        window[0].is_ascii_digit() && window[1].is_ascii_digit() && window[2] == b'/' && window[3].is_ascii_digit()
    })
}

fn contains_any(line: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| line.contains(needle))
}

fn sort_changes(changes: &mut [Change]) {
    changes.sort_by(|left, right| {
        right
            .severity
            .cmp(&left.severity)
            .then_with(|| left.category.cmp(&right.category))
            .then_with(|| left.original.cmp(&right.original))
    });
}

fn sort_modified_changes(changes: &mut [ModifiedChange]) {
    changes.sort_by(|left, right| {
        right
            .severity
            .cmp(&left.severity)
            .then_with(|| left.category.cmp(&right.category))
            .then_with(|| left.before.cmp(&right.before))
    });
}

fn match_modified_changes(added: &mut Vec<Change>, removed: &mut Vec<Change>) -> Vec<ModifiedChange> {
    let mut matched_removed = vec![false; removed.len()];
    let mut modified = Vec::new();
    let mut unmatched_added = Vec::new();

    for added_change in added.drain(..) {
        let mut best_index = None;
        let mut best_similarity = 0u16;

        for (index, removed_change) in removed.iter().enumerate() {
            if matched_removed[index] || removed_change.category != added_change.category {
                continue;
            }

            let similarity = similarity_score(&removed_change.original, &added_change.original);
            if similarity > best_similarity {
                best_similarity = similarity;
                best_index = Some(index);
            }
        }

        if let Some(index) = best_index.filter(|_| best_similarity >= 55) {
            matched_removed[index] = true;
            let before = removed[index].original.clone();
            let after = added_change.original.clone();
            modified.push(ModifiedChange {
                category: added_change.category,
                severity: added_change.severity.max(removed[index].severity),
                before,
                after,
                similarity: best_similarity,
            });
        } else {
            unmatched_added.push(added_change);
        }
    }

    let unmatched_removed = removed
        .iter()
        .enumerate()
        .filter_map(|(index, change)| (!matched_removed[index]).then_some(change.clone()))
        .collect::<Vec<_>>();

    *added = unmatched_added;
    *removed = unmatched_removed;
    sort_modified_changes(&mut modified);
    modified
}

fn similarity_score(left: &str, right: &str) -> u16 {
    let left_tokens = tokenize(left);
    let right_tokens = tokenize(right);
    if left_tokens.is_empty() || right_tokens.is_empty() {
        return 0;
    }

    let shared = left_tokens.iter().filter(|token| right_tokens.contains(*token)).count();
    let union = left_tokens.len() + right_tokens.len() - shared;
    if union == 0 {
        return 100;
    }

    let mut score = ((shared as f32 / union as f32) * 100.0).round() as u16;
    let shared_text_tokens = left_tokens
        .iter()
        .filter(|token| !token.chars().all(|character| character.is_ascii_digit()) && right_tokens.contains(*token))
        .count();
    if shared_text_tokens > 0 {
        score = score.max(60);
    }

    if left_tokens.first() == right_tokens.first() {
        score = score.max(65);
    }

    score
}

fn tokenize(input: &str) -> Vec<String> {
    input
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|token| !token.is_empty())
        .map(|token| token.to_lowercase())
        .collect()
}

fn render_markdown(before_path: &PathBuf, after_path: &PathBuf, report: &DiffReport) -> String {
    let critical = count_high_risk(report);
    let focus_changes = build_focus_changes(report);
    let mut lines = vec![
        "# Syllabus Diff Brief".to_string(),
        String::new(),
        format!("- Before: {}", before_path.display()),
        format!("- After: {}", after_path.display()),
        format!("- Added lines: {}", report.added.len()),
        format!("- Removed lines: {}", report.removed.len()),
        format!("- Modified lines: {}", report.modified.len()),
        format!("- High-risk changes: {critical}"),
        String::new(),
        "## Immediate Checks".to_string(),
    ];

    if focus_changes.is_empty() {
        lines.push("- No high-risk grading, exam, or date changes floated to the top.".to_string());
    } else {
        for line in &focus_changes {
            lines.push(format!("- {line}"));
        }
    }

    lines.extend([
        String::new(),
        "## Focus Areas".to_string(),
    ]);

    let category_rollup = summarize_categories(report);
    if category_rollup.is_empty() {
        lines.push("- No normalized line changes detected.".to_string());
    } else {
        for (category, count) in category_rollup {
            lines.push(format!(
                "- {}: {} changed line{}",
                category.label(),
                count,
                if count == 1 { "" } else { "s" }
            ));
        }
    }

    lines.push(String::new());
    lines.push("## Modified".to_string());
    push_modified_lines(&mut lines, &report.modified);
    lines.push(String::new());
    lines.push("## Added".to_string());
    push_change_lines(&mut lines, &report.added);
    lines.push(String::new());
    lines.push("## Removed".to_string());
    push_change_lines(&mut lines, &report.removed);
    lines.push(String::new());
    lines.push("## Follow-Up".to_string());
    lines.push(format!("- {}", follow_up_note(report)));
    lines.join("\n")
}

fn build_focus_changes(report: &DiffReport) -> Vec<String> {
    let mut focus = report
        .modified
        .iter()
        .filter(|change| change.severity == 3)
        .map(|change| {
            format!(
                "[{} | P{}] {} -> {}",
                change.category.label(),
                change.severity,
                change.before,
                change.after
            )
        })
        .collect::<Vec<_>>();

    focus.extend(
        report
            .added
            .iter()
            .filter(|change| change.severity == 3)
            .map(|change| format!("[{} | P{}] added: {}", change.category.label(), change.severity, change.original)),
    );
    focus.extend(
        report
            .removed
            .iter()
            .filter(|change| change.severity == 3)
            .map(|change| format!("[{} | P{}] removed: {}", change.category.label(), change.severity, change.original)),
    );

    focus.truncate(5);
    focus
}

fn push_change_lines(lines: &mut Vec<String>, changes: &[Change]) {
    if changes.is_empty() {
        lines.push("- None.".to_string());
        return;
    }

    for change in changes {
        lines.push(format!(
            "- [{} | P{}] {}",
            change.category.label(),
            change.severity,
            change.original
        ));
    }
}

fn push_modified_lines(lines: &mut Vec<String>, changes: &[ModifiedChange]) {
    if changes.is_empty() {
        lines.push("- None.".to_string());
        return;
    }

    for change in changes {
        lines.push(format!(
            "- [{} | P{} | {}% match] {} -> {}",
            change.category.label(),
            change.severity,
            change.similarity,
            change.before,
            change.after
        ));
    }
}

fn summarize_categories(report: &DiffReport) -> Vec<(Category, usize)> {
    let mut counts: BTreeMap<Category, usize> = BTreeMap::new();
    report.added.iter().chain(report.removed.iter()).for_each(|change| {
        *counts.entry(change.category).or_insert(0) += 1;
    });
    report.modified.iter().for_each(|change| {
        *counts.entry(change.category).or_insert(0) += 1;
    });
    counts.into_iter().collect()
}

fn follow_up_note(report: &DiffReport) -> String {
    let high_risk = count_high_risk(report);
    if high_risk > 0 {
        "Re-check grading weights, exam timing, and late-policy wording first; those are the easiest places for syllabus revisions to change student risk.".to_string()
    } else if !report.added.is_empty() || !report.removed.is_empty() {
        "Most changes look informational. Verify whether any schedule or attendance edits change your planning assumptions.".to_string()
    } else {
        "No normalized line changes were detected. If you expect differences, export both syllabi as plain text or markdown before rerunning.".to_string()
    }
}

fn count_high_risk(report: &DiffReport) -> usize {
    report
        .added
        .iter()
        .chain(report.removed.iter())
        .filter(|change| change.severity == 3)
        .count()
        + report
            .modified
            .iter()
            .filter(|change| change.severity == 3)
            .count()
}

fn render_json(before_path: &PathBuf, after_path: &PathBuf, report: &DiffReport) -> String {
    fn escape(value: &str) -> String {
        value
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n")
    }

    fn render_text_list(values: &[String]) -> String {
        values
            .iter()
            .map(|value| format!("\"{}\"", escape(value)))
            .collect::<Vec<_>>()
            .join(",")
    }

    fn render_changes(changes: &[Change]) -> String {
        changes
            .iter()
            .map(|change| {
                format!(
                    "{{\"category\":\"{}\",\"severity\":{},\"line\":\"{}\"}}",
                    change.category.label(),
                    change.severity,
                    escape(&change.original)
                )
            })
            .collect::<Vec<_>>()
            .join(",")
    }

    fn render_modified(changes: &[ModifiedChange]) -> String {
        changes
            .iter()
            .map(|change| {
                format!(
                    "{{\"category\":\"{}\",\"severity\":{},\"similarity\":{},\"before\":\"{}\",\"after\":\"{}\"}}",
                    change.category.label(),
                    change.severity,
                    change.similarity,
                    escape(&change.before),
                    escape(&change.after)
                )
            })
            .collect::<Vec<_>>()
            .join(",")
    }

    format!(
        concat!(
            "{{",
            "\"before\":\"{}\",",
            "\"after\":\"{}\",",
            "\"highRiskCount\":{},",
            "\"focusChanges\":[{}],",
            "\"modified\":[{}],",
            "\"added\":[{}],",
            "\"removed\":[{}]",
            "}}"
        ),
        escape(&before_path.display().to_string()),
        escape(&after_path.display().to_string()),
        count_high_risk(report),
        render_text_list(&build_focus_changes(report)),
        render_modified(&report.modified),
        render_changes(&report.added),
        render_changes(&report.removed)
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_normalized_lines() {
        let lines = extract_lines("## Grading\n- Homework 20%\n\n- Exams 50%");
        assert_eq!(lines.len(), 3);
        assert_eq!(lines[0].normalized, "grading");
        assert_eq!(lines[1].normalized, "homework 20%");
    }

    #[test]
    fn categorizes_high_risk_policy_changes() {
        let grading = build_change("Homework is now worth 35% of the final grade.");
        let attendance = build_change("Attendance is required for lab days.");
        assert_eq!(grading.category, Category::Grading);
        assert_eq!(grading.severity, 3);
        assert_eq!(attendance.category, Category::Attendance);
        assert_eq!(attendance.severity, 2);
    }

    #[test]
    fn diffs_added_and_removed_lines() {
        let before = "Homework 20%\nMidterm 25%\nAttendance optional";
        let after = "Homework 30%\nMidterm 25%\nAttendance required";
        let report = diff_texts(before, after);
        assert_eq!(report.modified.len(), 2);
        assert_eq!(report.added.len(), 0);
        assert_eq!(report.removed.len(), 0);
        assert!(report.modified.iter().any(|change| change.after.contains("30%")));
        assert!(report.modified.iter().any(|change| change.before.contains("optional")));
    }

    #[test]
    fn keeps_unrelated_lines_as_added_or_removed() {
        let before = "Attendance optional";
        let after = "Bring laptop to every lab session";
        let report = diff_texts(before, after);
        assert_eq!(report.modified.len(), 0);
        assert_eq!(report.added.len(), 1);
        assert_eq!(report.removed.len(), 1);
    }

    #[test]
    fn builds_focus_list_from_high_risk_changes() {
        let before = "Homework 20%\nMidterm on 09/10";
        let after = "Homework 35%\nMidterm on 09/17";
        let report = diff_texts(before, after);
        let focus = build_focus_changes(&report);
        assert_eq!(focus.len(), 2);
        assert!(focus.iter().any(|line| line.contains("Homework 20% -> Homework 35%")));
        assert!(focus.iter().any(|line| line.contains("Midterm on 09/10 -> Midterm on 09/17")));
    }
}
