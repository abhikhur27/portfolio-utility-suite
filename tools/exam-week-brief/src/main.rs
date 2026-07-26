use chrono::{Datelike, Duration, NaiveDate, NaiveTime, Weekday};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::env;
use std::error::Error;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
struct ExamRow {
    course: String,
    exam_date: String,
    start_time: String,
    end_time: String,
    location: String,
    #[serde(default)]
    prep_hours: Option<f64>,
}

#[derive(Debug, Clone)]
struct Exam {
    course: String,
    exam_date: NaiveDate,
    start_time: NaiveTime,
    end_time: NaiveTime,
    location: String,
    prep_hours: f64,
}

#[derive(Debug, Serialize)]
struct Conflict {
    courses: [String; 2],
    date: String,
    overlap_minutes: i64,
}

#[derive(Debug, Serialize)]
struct TightTurnaround {
    first_course: String,
    second_course: String,
    date: String,
    gap_minutes: i64,
}

#[derive(Debug, Serialize)]
struct DailySummary {
    date: String,
    exam_count: usize,
    exam_minutes: i64,
}

#[derive(Debug, Serialize)]
struct PrepLoad {
    date: String,
    prep_hours: f64,
    overloaded: bool,
}

#[derive(Debug, Serialize)]
struct UnallocatedPrep {
    course: String,
    exam_date: String,
    missing_hours: f64,
}

#[derive(Debug, Serialize)]
struct FocusLane {
    course: String,
    exam_date: String,
    days_until_exam: i64,
    prep_hours: f64,
    prep_intensity: f64,
}

#[derive(Debug, Serialize)]
struct Brief {
    exams: usize,
    conflicts: Vec<Conflict>,
    tight_turnarounds: Vec<TightTurnaround>,
    day_summaries: Vec<DailySummary>,
    prep_loads: Vec<PrepLoad>,
    unallocated_prep: Vec<UnallocatedPrep>,
    focus_order: Vec<FocusLane>,
    daily_cap: f64,
    prep_window_days: i64,
    blocked_dates: Vec<String>,
    blocked_weekdays: Vec<String>,
}

#[derive(Debug)]
struct Config {
    input: PathBuf,
    markdown_out: Option<PathBuf>,
    json_out: Option<PathBuf>,
    prep_window_days: i64,
    daily_cap: f64,
    today: NaiveDate,
    blocked_dates: Vec<NaiveDate>,
    blocked_weekdays: Vec<Weekday>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let config = parse_args(env::args().skip(1).collect())?;
    let exams = load_exams(&config.input)?;
    if exams.is_empty() {
        return Err("Input CSV did not contain any exam rows.".into());
    }

    let brief = build_brief(
        &exams,
        config.daily_cap,
        config.prep_window_days,
        config.today,
        &config.blocked_dates,
        &config.blocked_weekdays,
    );
    let markdown = render_markdown(&brief, &exams);

    println!("{markdown}");

    if let Some(path) = &config.markdown_out {
        write_text(path, &markdown)?;
    }
    if let Some(path) = &config.json_out {
        write_text(path, &serde_json::to_string_pretty(&brief)?)?;
    }

    Ok(())
}

fn parse_args(args: Vec<String>) -> Result<Config, Box<dyn Error>> {
    if args.is_empty() || args.iter().any(|arg| arg == "--help" || arg == "-h") {
        print_help();
        std::process::exit(0);
    }

    let mut input = None;
    let mut markdown_out = None;
    let mut json_out = None;
    let mut prep_window_days = 5_i64;
    let mut daily_cap = 3.5_f64;
    let mut today = chrono::Local::now().date_naive();
    let mut blocked_dates = Vec::new();
    let mut blocked_weekdays = Vec::new();

    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--input" => {
                input = Some(next_path(&args, &mut index, "--input")?);
            }
            "--markdown" => {
                markdown_out = Some(next_path(&args, &mut index, "--markdown")?);
            }
            "--json" => {
                json_out = Some(next_path(&args, &mut index, "--json")?);
            }
            "--prep-window-days" => {
                prep_window_days = next_value(&args, &mut index, "--prep-window-days")?.parse()?;
                if prep_window_days <= 0 {
                    return Err("--prep-window-days must be positive.".into());
                }
            }
            "--daily-cap" => {
                daily_cap = next_value(&args, &mut index, "--daily-cap")?.parse()?;
                if daily_cap <= 0.0 {
                    return Err("--daily-cap must be positive.".into());
                }
            }
            "--today" => {
                let raw = next_value(&args, &mut index, "--today")?;
                today = NaiveDate::parse_from_str(raw, "%Y-%m-%d")?;
            }
            "--blocked-date" => {
                let raw = next_value(&args, &mut index, "--blocked-date")?;
                blocked_dates.push(NaiveDate::parse_from_str(raw, "%Y-%m-%d")?);
            }
            "--blocked-weekday" => {
                let raw = next_value(&args, &mut index, "--blocked-weekday")?;
                blocked_weekdays.push(parse_weekday(raw)?);
            }
            other => {
                return Err(format!("Unknown argument: {other}").into());
            }
        }
        index += 1;
    }

    Ok(Config {
        input: input.ok_or("Missing required --input path.")?,
        markdown_out,
        json_out,
        prep_window_days,
        daily_cap,
        today,
        blocked_dates,
        blocked_weekdays,
    })
}

fn parse_weekday(raw: &str) -> Result<Weekday, Box<dyn Error>> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "mon" | "monday" => Ok(Weekday::Mon),
        "tue" | "tues" | "tuesday" => Ok(Weekday::Tue),
        "wed" | "wednesday" => Ok(Weekday::Wed),
        "thu" | "thur" | "thurs" | "thursday" => Ok(Weekday::Thu),
        "fri" | "friday" => Ok(Weekday::Fri),
        "sat" | "saturday" => Ok(Weekday::Sat),
        "sun" | "sunday" => Ok(Weekday::Sun),
        _ => Err(format!("Unsupported weekday: {raw}").into()),
    }
}

fn next_path(args: &[String], index: &mut usize, flag: &str) -> Result<PathBuf, Box<dyn Error>> {
    Ok(PathBuf::from(next_value(args, index, flag)?))
}

fn next_value<'a>(
    args: &'a [String],
    index: &mut usize,
    flag: &str,
) -> Result<&'a str, Box<dyn Error>> {
    *index += 1;
    args.get(*index)
        .map(String::as_str)
        .ok_or_else(|| format!("Missing value for {flag}.").into())
}

fn print_help() {
    println!(
        "Exam Week Brief\n\
         \n\
         Usage:\n\
           cargo run -- --input sample_exams.csv [--markdown report.md] [--json report.json]\n\
         \n\
         Options:\n\
           --input PATH             CSV with course, exam_date, start_time, end_time, location, prep_hours\n\
           --markdown PATH          Optional markdown report output path\n\
           --json PATH              Optional JSON output path\n\
           --prep-window-days N     Days before each exam used for prep backplanning (default: 5)\n\
           --daily-cap HOURS        Prep-hour threshold used to flag overloaded days (default: 3.5)\n\
           --today YYYY-MM-DD       Override today's date for reproducible planning\n\
           --blocked-date DATE      Exclude a date from prep backplanning; repeatable\n\
           --blocked-weekday DAY    Exclude a weekday like sat, sunday, mon; repeatable\n"
    );
}

fn load_exams(path: &Path) -> Result<Vec<Exam>, Box<dyn Error>> {
    let mut reader = csv::Reader::from_path(path)?;
    let mut exams = Vec::new();

    for row in reader.deserialize::<ExamRow>() {
        let raw = row?;
        let exam_date = NaiveDate::parse_from_str(raw.exam_date.trim(), "%Y-%m-%d")?;
        let start_time = NaiveTime::parse_from_str(raw.start_time.trim(), "%H:%M")?;
        let end_time = NaiveTime::parse_from_str(raw.end_time.trim(), "%H:%M")?;
        if end_time <= start_time {
            return Err(format!(
                "{} has an end time that is not after the start time.",
                raw.course
            )
            .into());
        }

        exams.push(Exam {
            course: raw.course.trim().to_string(),
            exam_date,
            start_time,
            end_time,
            location: raw.location.trim().to_string(),
            prep_hours: raw.prep_hours.unwrap_or(4.0).max(0.0),
        });
    }

    exams.sort_by_key(|exam| (exam.exam_date, exam.start_time, exam.course.clone()));
    Ok(exams)
}

fn build_brief(
    exams: &[Exam],
    daily_cap: f64,
    prep_window_days: i64,
    today: NaiveDate,
    blocked_dates: &[NaiveDate],
    blocked_weekdays: &[Weekday],
) -> Brief {
    let (prep_loads, unallocated_prep) = build_prep_loads(
        exams,
        daily_cap,
        prep_window_days,
        today,
        blocked_dates,
        blocked_weekdays,
    );
    Brief {
        exams: exams.len(),
        conflicts: detect_conflicts(exams),
        tight_turnarounds: detect_tight_turnarounds(exams, 90),
        day_summaries: summarize_days(exams),
        prep_loads,
        unallocated_prep,
        focus_order: build_focus_order(exams, today),
        daily_cap,
        prep_window_days,
        blocked_dates: blocked_dates.iter().map(|date| date.to_string()).collect(),
        blocked_weekdays: blocked_weekdays
            .iter()
            .map(|weekday| weekday_label(*weekday).to_string())
            .collect(),
    }
}

fn weekday_label(weekday: Weekday) -> &'static str {
    match weekday {
        Weekday::Mon => "Monday",
        Weekday::Tue => "Tuesday",
        Weekday::Wed => "Wednesday",
        Weekday::Thu => "Thursday",
        Weekday::Fri => "Friday",
        Weekday::Sat => "Saturday",
        Weekday::Sun => "Sunday",
    }
}

fn detect_conflicts(exams: &[Exam]) -> Vec<Conflict> {
    let mut conflicts = Vec::new();
    for left_index in 0..exams.len() {
        for right_index in (left_index + 1)..exams.len() {
            let left = &exams[left_index];
            let right = &exams[right_index];
            if left.exam_date != right.exam_date {
                break;
            }
            let overlap_start = left.start_time.max(right.start_time);
            let overlap_end = left.end_time.min(right.end_time);
            let overlap_minutes = (overlap_end - overlap_start).num_minutes();
            if overlap_minutes > 0 {
                conflicts.push(Conflict {
                    courses: [left.course.clone(), right.course.clone()],
                    date: left.exam_date.to_string(),
                    overlap_minutes,
                });
            }
        }
    }
    conflicts
}

fn detect_tight_turnarounds(exams: &[Exam], threshold_minutes: i64) -> Vec<TightTurnaround> {
    let mut turnarounds = Vec::new();
    for pair in exams.windows(2) {
        let first = &pair[0];
        let second = &pair[1];
        if first.exam_date != second.exam_date {
            continue;
        }
        let gap_minutes = (second.start_time - first.end_time).num_minutes();
        if gap_minutes >= 0 && gap_minutes < threshold_minutes {
            turnarounds.push(TightTurnaround {
                first_course: first.course.clone(),
                second_course: second.course.clone(),
                date: first.exam_date.to_string(),
                gap_minutes,
            });
        }
    }
    turnarounds
}

fn summarize_days(exams: &[Exam]) -> Vec<DailySummary> {
    let mut day_map: BTreeMap<NaiveDate, (usize, i64)> = BTreeMap::new();
    for exam in exams {
        let entry = day_map.entry(exam.exam_date).or_insert((0, 0));
        entry.0 += 1;
        entry.1 += (exam.end_time - exam.start_time).num_minutes();
    }

    day_map
        .into_iter()
        .map(|(date, (exam_count, exam_minutes))| DailySummary {
            date: date.to_string(),
            exam_count,
            exam_minutes,
        })
        .collect()
}

fn build_prep_loads(
    exams: &[Exam],
    daily_cap: f64,
    prep_window_days: i64,
    today: NaiveDate,
    blocked_dates: &[NaiveDate],
    blocked_weekdays: &[Weekday],
) -> (Vec<PrepLoad>, Vec<UnallocatedPrep>) {
    let mut loads: BTreeMap<NaiveDate, f64> = BTreeMap::new();
    let blocked_dates: BTreeSet<NaiveDate> = blocked_dates.iter().copied().collect();
    let blocked_weekdays: HashSet<Weekday> = blocked_weekdays.iter().copied().collect();
    let mut unallocated_prep = Vec::new();

    for exam in exams {
        let start_date = exam.exam_date - Duration::days(prep_window_days);
        let active_days: Vec<NaiveDate> = (0..prep_window_days)
            .map(|offset| start_date + Duration::days(offset))
            .filter(|date| {
                *date >= today
                    && *date < exam.exam_date
                    && !blocked_dates.contains(date)
                    && !blocked_weekdays.contains(&date.weekday())
            })
            .collect();

        if active_days.is_empty() {
            unallocated_prep.push(UnallocatedPrep {
                course: exam.course.clone(),
                exam_date: exam.exam_date.to_string(),
                missing_hours: round_two(exam.prep_hours),
            });
            continue;
        }

        let per_day = exam.prep_hours / active_days.len() as f64;
        for date in active_days {
            *loads.entry(date).or_insert(0.0) += per_day;
        }
    }

    (
        loads
            .iter()
            .map(|(date, prep_hours)| PrepLoad {
                date: date.to_string(),
                prep_hours: round_two(*prep_hours),
                overloaded: *prep_hours > daily_cap,
        })
        .collect(),
        unallocated_prep,
    )
}

fn build_focus_order(exams: &[Exam], today: NaiveDate) -> Vec<FocusLane> {
    let mut lanes = exams
        .iter()
        .map(|exam| {
            let days_until_exam = (exam.exam_date - today).num_days();
            let days_for_prep = days_until_exam.max(1) as f64;
            FocusLane {
                course: exam.course.clone(),
                exam_date: exam.exam_date.to_string(),
                days_until_exam,
                prep_hours: round_two(exam.prep_hours),
                prep_intensity: round_two(exam.prep_hours / days_for_prep),
            }
        })
        .collect::<Vec<_>>();

    lanes.sort_by(|left, right| {
        left.days_until_exam
            .cmp(&right.days_until_exam)
            .then_with(|| {
                right
                    .prep_intensity
                    .partial_cmp(&left.prep_intensity)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });
    lanes
}

fn render_markdown(brief: &Brief, exams: &[Exam]) -> String {
    let mut out = String::new();
    writeln!(&mut out, "# Exam Week Brief").ok();
    writeln!(&mut out).ok();
    writeln!(&mut out, "- Exams loaded: {}", brief.exams).ok();
    writeln!(&mut out, "- Prep window: {} day(s)", brief.prep_window_days).ok();
    writeln!(&mut out, "- Daily prep cap: {:.1} hour(s)", brief.daily_cap).ok();
    if !brief.blocked_dates.is_empty() {
        writeln!(
            &mut out,
            "- Blocked prep dates: {}",
            brief.blocked_dates.join(", ")
        )
        .ok();
    }
    if !brief.blocked_weekdays.is_empty() {
        writeln!(
            &mut out,
            "- Blocked prep weekdays: {}",
            brief.blocked_weekdays.join(", ")
        )
        .ok();
    }
    writeln!(&mut out).ok();

    writeln!(&mut out, "## Exam Schedule").ok();
    for exam in exams {
        let duration_minutes = (exam.end_time - exam.start_time).num_minutes();
        writeln!(
            &mut out,
            "- {} | {} {}-{} | {} | {:.1}h prep | {} min",
            exam.course,
            exam.exam_date,
            exam.start_time.format("%H:%M"),
            exam.end_time.format("%H:%M"),
            exam.location,
            exam.prep_hours,
            duration_minutes
        )
        .ok();
    }
    writeln!(&mut out).ok();

    writeln!(&mut out, "## Conflict Watch").ok();
    if brief.conflicts.is_empty() {
        writeln!(&mut out, "- No overlapping exams detected.").ok();
    } else {
        for conflict in &brief.conflicts {
            writeln!(
                &mut out,
                "- {} vs {} on {} overlaps by {} minutes.",
                conflict.courses[0], conflict.courses[1], conflict.date, conflict.overlap_minutes
            )
            .ok();
        }
    }
    if brief.tight_turnarounds.is_empty() {
        writeln!(
            &mut out,
            "- No tight same-day turnarounds under 90 minutes."
        )
        .ok();
    } else {
        for turnaround in &brief.tight_turnarounds {
            writeln!(
                &mut out,
                "- {} -> {} on {} leaves only {} minutes.",
                turnaround.first_course,
                turnaround.second_course,
                turnaround.date,
                turnaround.gap_minutes
            )
            .ok();
        }
    }
    writeln!(&mut out).ok();

    writeln!(&mut out, "## Day Load").ok();
    for day in &brief.day_summaries {
        writeln!(
            &mut out,
            "- {}: {} exam(s), {} total exam minutes.",
            day.date, day.exam_count, day.exam_minutes
        )
        .ok();
    }
    writeln!(&mut out).ok();

    writeln!(&mut out, "## Prep Load").ok();
    if brief.prep_loads.is_empty() {
        writeln!(
            &mut out,
            "- No future prep days were generated from the current exam dates."
        )
        .ok();
    } else {
        for load in &brief.prep_loads {
            writeln!(
                &mut out,
                "- {}: {:.2}h{}",
                load.date,
                load.prep_hours,
                if load.overloaded { " (over cap)" } else { "" }
            )
            .ok();
        }
    }
    writeln!(&mut out).ok();

    if !brief.unallocated_prep.is_empty() {
        writeln!(&mut out, "## Prep Gaps").ok();
        for gap in &brief.unallocated_prep {
            writeln!(
                &mut out,
                "- {} before {} still has {:.2}h with no available prep day.",
                gap.course, gap.exam_date, gap.missing_hours
            )
            .ok();
        }
        writeln!(&mut out).ok();
    }

    writeln!(&mut out, "## Focus Order").ok();
    for focus in &brief.focus_order {
        writeln!(
            &mut out,
            "1. {} | exam {} | {} day(s) out | {:.2}h total prep | {:.2}h/day intensity",
            focus.course,
            focus.exam_date,
            focus.days_until_exam,
            focus.prep_hours,
            focus.prep_intensity
        )
        .ok();
    }

    out
}

fn write_text(path: &Path, content: &str) -> Result<(), Box<dyn Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, content)?;
    Ok(())
}

fn round_two(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn exam(course: &str, date: &str, start: &str, end: &str, prep_hours: f64) -> Exam {
        Exam {
            course: course.to_string(),
            exam_date: NaiveDate::parse_from_str(date, "%Y-%m-%d").unwrap(),
            start_time: NaiveTime::parse_from_str(start, "%H:%M").unwrap(),
            end_time: NaiveTime::parse_from_str(end, "%H:%M").unwrap(),
            location: "ECSS".to_string(),
            prep_hours,
        }
    }

    #[test]
    fn overlap_detection_catches_same_day_collision() {
        let exams = vec![
            exam("CS 3345", "2026-12-14", "09:00", "11:00", 4.0),
            exam("MATH 2418", "2026-12-14", "10:30", "12:00", 3.0),
        ];

        let conflicts = detect_conflicts(&exams);
        assert_eq!(conflicts.len(), 1);
        assert_eq!(conflicts[0].overlap_minutes, 30);
    }

    #[test]
    fn turnaround_detection_flags_short_gap() {
        let exams = vec![
            exam("CS 3345", "2026-12-14", "09:00", "11:00", 4.0),
            exam("PHYS 2325", "2026-12-14", "11:45", "13:15", 2.0),
        ];

        let turnarounds = detect_tight_turnarounds(&exams, 90);
        assert_eq!(turnarounds.len(), 1);
        assert_eq!(turnarounds[0].gap_minutes, 45);
    }

    #[test]
    fn prep_loads_spread_backward_over_window() {
        let exams = vec![exam("CS 3345", "2026-12-14", "09:00", "11:00", 6.0)];
        let loads = build_prep_loads(
            &exams,
            3.0,
            3,
            NaiveDate::parse_from_str("2026-12-10", "%Y-%m-%d").unwrap(),
            &[],
            &[],
        );

        assert_eq!(loads.0.len(), 3);
        assert!(loads.0.iter().all(|row| (row.prep_hours - 2.0).abs() < 1e-9));
    }

    #[test]
    fn blocked_dates_can_force_unallocated_prep() {
        let exams = vec![exam("CS 3345", "2026-12-14", "09:00", "11:00", 6.0)];
        let blocked_dates = vec![
            NaiveDate::parse_from_str("2026-12-11", "%Y-%m-%d").unwrap(),
            NaiveDate::parse_from_str("2026-12-12", "%Y-%m-%d").unwrap(),
            NaiveDate::parse_from_str("2026-12-13", "%Y-%m-%d").unwrap(),
        ];
        let loads = build_prep_loads(
            &exams,
            3.0,
            3,
            NaiveDate::parse_from_str("2026-12-10", "%Y-%m-%d").unwrap(),
            &blocked_dates,
            &[],
        );

        assert!(loads.0.is_empty());
        assert_eq!(loads.1.len(), 1);
        assert!((loads.1[0].missing_hours - 6.0).abs() < 1e-9);
    }

    #[test]
    fn blocked_weekdays_skip_weekend_prep_days() {
        let exams = vec![exam("CS 3345", "2026-12-14", "09:00", "11:00", 6.0)];
        let loads = build_prep_loads(
            &exams,
            4.0,
            3,
            NaiveDate::parse_from_str("2026-12-11", "%Y-%m-%d").unwrap(),
            &[],
            &[Weekday::Sat, Weekday::Sun],
        );

        assert_eq!(loads.0.len(), 1);
        assert_eq!(loads.0[0].date, "2026-12-11");
        assert!((loads.0[0].prep_hours - 6.0).abs() < 1e-9);
    }
}
