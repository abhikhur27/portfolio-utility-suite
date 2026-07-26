use std::cmp::{max, min};
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

use chrono::{Duration, NaiveDate, NaiveDateTime, NaiveTime};
use clap::Parser;
use serde::Serialize;

#[derive(Parser, Debug)]
#[command(
    name = "calendar-conflict-scout",
    about = "Scan one or more ICS calendars for overlaps, tight turnarounds, and free windows."
)]
struct Cli {
    #[arg(short, long = "input", required = true)]
    inputs: Vec<PathBuf>,

    #[arg(long, help = "Start date in YYYY-MM-DD format.")]
    start: NaiveDate,

    #[arg(long, help = "End date in YYYY-MM-DD format. Defaults to the start date.")]
    end: Option<NaiveDate>,

    #[arg(long, default_value = "08:00", value_parser = parse_clock)]
    day_start: NaiveTime,

    #[arg(long, default_value = "22:00", value_parser = parse_clock)]
    day_end: NaiveTime,

    #[arg(long, default_value_t = 30)]
    min_gap_minutes: i64,

    #[arg(long)]
    markdown_out: Option<PathBuf>,

    #[arg(long)]
    json_out: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct Event {
    calendar: String,
    summary: String,
    location: Option<String>,
    start: NaiveDateTime,
    end: NaiveDateTime,
    all_day: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct ConflictWindow {
    start: NaiveDateTime,
    end: NaiveDateTime,
    left: Event,
    right: Event,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct TightTurnaround {
    gap_minutes: i64,
    earlier: Event,
    later: Event,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct FreeWindow {
    day: NaiveDate,
    start: NaiveDateTime,
    end: NaiveDateTime,
    duration_minutes: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct BusyDay {
    day: NaiveDate,
    event_count: usize,
    busy_minutes: i64,
    longest_free_window_minutes: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct Summary {
    calendars_scanned: usize,
    total_events: usize,
    conflict_count: usize,
    tight_turnaround_count: usize,
    free_window_count: usize,
    range_start: NaiveDate,
    range_end: NaiveDate,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct Report {
    summary: Summary,
    events: Vec<Event>,
    conflicts: Vec<ConflictWindow>,
    tight_turnarounds: Vec<TightTurnaround>,
    free_windows: Vec<FreeWindow>,
    busy_days: Vec<BusyDay>,
}

fn parse_clock(raw: &str) -> Result<NaiveTime, String> {
    NaiveTime::parse_from_str(raw, "%H:%M")
        .map_err(|_| format!("Invalid clock value '{raw}'. Use HH:MM."))
}

fn unfold_ics_lines(raw: &str) -> Vec<String> {
    let normalized = raw.replace("\r\n", "\n").replace('\r', "\n");
    let mut lines: Vec<String> = Vec::new();

    for line in normalized.lines() {
        if let Some(last) = lines.last_mut() {
            if line.starts_with(' ') || line.starts_with('\t') {
                last.push_str(line.trim_start());
                continue;
            }
        }
        lines.push(line.to_string());
    }

    lines
}

fn parse_datetime_value(value: &str) -> Result<(NaiveDateTime, bool), String> {
    if value.len() == 8 {
        let date = NaiveDate::parse_from_str(value, "%Y%m%d")
            .map_err(|_| format!("Invalid all-day date '{value}'"))?;
        return Ok((date.and_time(NaiveTime::MIN), true));
    }

    if let Some(trimmed) = value.strip_suffix('Z') {
        return NaiveDateTime::parse_from_str(trimmed, "%Y%m%dT%H%M%S")
            .map(|parsed| (parsed, false))
            .map_err(|_| format!("Invalid UTC datetime '{value}'"));
    }

    NaiveDateTime::parse_from_str(value, "%Y%m%dT%H%M%S")
        .map(|parsed| (parsed, false))
        .map_err(|_| format!("Invalid datetime '{value}'"))
}

fn value_after_colon(line: &str) -> Option<&str> {
    line.split_once(':').map(|(_, value)| value)
}

fn property_name(line: &str) -> &str {
    line.split_once(':')
        .map(|(left, _)| left)
        .unwrap_or(line)
        .split(';')
        .next()
        .unwrap_or(line)
}

fn parse_ics_events(path: &Path) -> Result<Vec<Event>, Box<dyn Error>> {
    let raw = fs::read_to_string(path)?;
    let calendar = path
        .file_stem()
        .and_then(|stem| stem.to_str())
        .unwrap_or("calendar")
        .to_string();
    let lines = unfold_ics_lines(&raw);
    let mut events = Vec::new();
    let mut inside_event = false;
    let mut summary: Option<String> = None;
    let mut location: Option<String> = None;
    let mut start: Option<(NaiveDateTime, bool)> = None;
    let mut end: Option<(NaiveDateTime, bool)> = None;

    for line in lines {
        match line.as_str() {
            "BEGIN:VEVENT" => {
                inside_event = true;
                summary = None;
                location = None;
                start = None;
                end = None;
            }
            "END:VEVENT" => {
                if inside_event {
                    if let Some((start_at, all_day)) = start {
                        let end_at = if let Some((end_value, _)) = end {
                            end_value
                        } else if all_day {
                            start_at + Duration::days(1)
                        } else {
                            start_at + Duration::minutes(30)
                        };
                        if end_at > start_at {
                            events.push(Event {
                                calendar: calendar.clone(),
                                summary: summary.clone().unwrap_or_else(|| "Untitled event".to_string()),
                                location: location.clone(),
                                start: start_at,
                                end: end_at,
                                all_day,
                            });
                        }
                    }
                }
                inside_event = false;
            }
            _ if inside_event => {
                let Some(value) = value_after_colon(&line) else {
                    continue;
                };
                match property_name(&line) {
                    "SUMMARY" => summary = Some(value.trim().to_string()),
                    "LOCATION" => location = Some(value.trim().to_string()),
                    "DTSTART" => start = Some(parse_datetime_value(value)?),
                    "DTEND" => end = Some(parse_datetime_value(value)?),
                    _ => {}
                }
            }
            _ => {}
        }
    }

    Ok(events)
}

fn clip_event_to_range(event: &Event, range_start: NaiveDateTime, range_end: NaiveDateTime) -> Option<Event> {
    let start = max(event.start, range_start);
    let end = min(event.end, range_end);
    if end <= start {
        return None;
    }
    Some(Event {
        start,
        end,
        ..event.clone()
    })
}

fn detect_conflicts(events: &[Event]) -> Vec<ConflictWindow> {
    let mut conflicts = Vec::new();
    for (index, left) in events.iter().enumerate() {
        for right in events.iter().skip(index + 1) {
            if right.start >= left.end {
                break;
            }
            let overlap_start = max(left.start, right.start);
            let overlap_end = min(left.end, right.end);
            if overlap_end > overlap_start {
                conflicts.push(ConflictWindow {
                    start: overlap_start,
                    end: overlap_end,
                    left: left.clone(),
                    right: right.clone(),
                });
            }
        }
    }
    conflicts
}

fn detect_tight_turnarounds(events: &[Event], min_gap_minutes: i64) -> Vec<TightTurnaround> {
    let mut turnarounds = Vec::new();
    for pair in events.windows(2) {
        let [earlier, later] = pair else {
            continue;
        };
        if later.start < earlier.end {
            continue;
        }
        let gap_minutes = (later.start - earlier.end).num_minutes();
        if gap_minutes <= min_gap_minutes {
            turnarounds.push(TightTurnaround {
                gap_minutes,
                earlier: earlier.clone(),
                later: later.clone(),
            });
        }
    }
    turnarounds
}

fn compute_free_windows(
    events: &[Event],
    start_date: NaiveDate,
    end_date: NaiveDate,
    day_start: NaiveTime,
    day_end: NaiveTime,
) -> Vec<FreeWindow> {
    let mut windows = Vec::new();
    let mut day = start_date;

    while day <= end_date {
        let day_window_start = day.and_time(day_start);
        let day_window_end = day.and_time(day_end);
        let mut cursor = day_window_start;

        let mut day_events: Vec<Event> = events
            .iter()
            .filter_map(|event| clip_event_to_range(event, day_window_start, day_window_end))
            .collect();
        day_events.sort_by_key(|event| event.start);

        for event in day_events {
            if event.start > cursor {
                let duration_minutes = (event.start - cursor).num_minutes();
                windows.push(FreeWindow {
                    day,
                    start: cursor,
                    end: event.start,
                    duration_minutes,
                });
            }
            if event.end > cursor {
                cursor = event.end;
            }
        }

        if day_window_end > cursor {
            windows.push(FreeWindow {
                day,
                start: cursor,
                end: day_window_end,
                duration_minutes: (day_window_end - cursor).num_minutes(),
            });
        }

        day = day.succ_opt().expect("date increment should stay valid");
    }

    windows
}

fn summarize_busy_days(
    events: &[Event],
    free_windows: &[FreeWindow],
    start_date: NaiveDate,
    end_date: NaiveDate,
    day_start: NaiveTime,
    day_end: NaiveTime,
) -> Vec<BusyDay> {
    let mut days = Vec::new();
    let mut day = start_date;
    let available_minutes = (day_end - day_start).num_minutes();

    while day <= end_date {
        let day_window_start = day.and_time(day_start);
        let day_window_end = day.and_time(day_end);
        let day_event_count = events
            .iter()
            .filter(|event| event.end > day_window_start && event.start < day_window_end)
            .count();
        let free_minutes: i64 = free_windows
            .iter()
            .filter(|window| window.day == day)
            .map(|window| window.duration_minutes)
            .sum();
        let longest_free_window_minutes = free_windows
            .iter()
            .filter(|window| window.day == day)
            .map(|window| window.duration_minutes)
            .max()
            .unwrap_or(0);

        days.push(BusyDay {
            day,
            event_count: day_event_count,
            busy_minutes: available_minutes - free_minutes,
            longest_free_window_minutes,
        });

        day = day.succ_opt().expect("date increment should stay valid");
    }

    days
}

fn format_event(event: &Event) -> String {
    let timing = if event.all_day {
        format!("{} (all day)", event.start.date())
    } else {
        format!(
            "{} {}-{}",
            event.start.date(),
            event.start.time().format("%H:%M"),
            event.end.time().format("%H:%M")
        )
    };
    match &event.location {
        Some(location) if !location.is_empty() => format!("{timing} | {} | {} | {}", event.calendar, event.summary, location),
        _ => format!("{timing} | {} | {}", event.calendar, event.summary),
    }
}

fn render_markdown(report: &Report) -> String {
    let mut lines = vec![
        "# Calendar Conflict Scout Report".to_string(),
        String::new(),
        format!(
            "- Range: {} to {}",
            report.summary.range_start,
            report.summary.range_end
        ),
        format!("- Calendars scanned: {}", report.summary.calendars_scanned),
        format!("- Events in range: {}", report.summary.total_events),
        format!("- Conflicts: {}", report.summary.conflict_count),
        format!(
            "- Tight turnarounds: {}",
            report.summary.tight_turnaround_count
        ),
        format!("- Free windows: {}", report.summary.free_window_count),
        String::new(),
        "## Conflicts".to_string(),
        String::new(),
    ];

    if report.conflicts.is_empty() {
        lines.push("- No overlaps detected.".to_string());
    } else {
        for conflict in &report.conflicts {
            lines.push(format!(
                "- {} {}-{} | {} <-> {}",
                conflict.start.date(),
                conflict.start.time().format("%H:%M"),
                conflict.end.time().format("%H:%M"),
                conflict.left.summary,
                conflict.right.summary
            ));
        }
    }

    lines.extend([String::new(), "## Tight Turnarounds".to_string(), String::new()]);
    if report.tight_turnarounds.is_empty() {
        lines.push("- No short turnarounds inside the configured threshold.".to_string());
    } else {
        for turnaround in &report.tight_turnarounds {
            lines.push(format!(
                "- {} minutes between {} and {}",
                turnaround.gap_minutes, turnaround.earlier.summary, turnaround.later.summary
            ));
        }
    }

    lines.extend([String::new(), "## Free Windows".to_string(), String::new()]);
    if report.free_windows.is_empty() {
        lines.push("- No free windows inside the requested day bounds.".to_string());
    } else {
        for window in &report.free_windows {
            lines.push(format!(
                "- {} | {}-{} | {} minutes",
                window.day,
                window.start.time().format("%H:%M"),
                window.end.time().format("%H:%M"),
                window.duration_minutes
            ));
        }
    }

    lines.extend([String::new(), "## Busy Days".to_string(), String::new()]);
    if report.busy_days.is_empty() {
        lines.push("- No day summaries available.".to_string());
    } else {
        for day in &report.busy_days {
            lines.push(format!(
                "- {} | {} events | busy {} minutes | longest free window {} minutes",
                day.day, day.event_count, day.busy_minutes, day.longest_free_window_minutes
            ));
        }
    }

    lines.extend([String::new(), "## Events".to_string(), String::new()]);
    for event in &report.events {
        lines.push(format!("- {}", format_event(event)));
    }

    lines.join("\n")
}

fn build_report(cli: &Cli) -> Result<Report, Box<dyn Error>> {
    let end_date = cli.end.unwrap_or(cli.start);
    if end_date < cli.start {
        return Err("end date must be on or after start date".into());
    }
    if cli.day_end <= cli.day_start {
        return Err("day-end must be later than day-start".into());
    }

    let range_start = cli.start.and_time(NaiveTime::MIN);
    let range_end = end_date
        .succ_opt()
        .ok_or("date range overflow")?
        .and_time(NaiveTime::MIN);

    let mut events = Vec::new();
    for input in &cli.inputs {
        let parsed = parse_ics_events(input)?;
        events.extend(parsed);
    }

    let mut clipped_events: Vec<Event> = events
        .iter()
        .filter_map(|event| clip_event_to_range(event, range_start, range_end))
        .collect();
    clipped_events.sort_by_key(|event| (event.start, event.end, event.summary.clone()));

    let conflicts = detect_conflicts(&clipped_events);
    let tight_turnarounds = detect_tight_turnarounds(&clipped_events, cli.min_gap_minutes);
    let free_windows = compute_free_windows(
        &clipped_events,
        cli.start,
        end_date,
        cli.day_start,
        cli.day_end,
    );
    let busy_days = summarize_busy_days(
        &clipped_events,
        &free_windows,
        cli.start,
        end_date,
        cli.day_start,
        cli.day_end,
    );

    Ok(Report {
        summary: Summary {
            calendars_scanned: cli.inputs.len(),
            total_events: clipped_events.len(),
            conflict_count: conflicts.len(),
            tight_turnaround_count: tight_turnarounds.len(),
            free_window_count: free_windows.len(),
            range_start: cli.start,
            range_end: end_date,
        },
        events: clipped_events,
        conflicts,
        tight_turnarounds,
        free_windows,
        busy_days,
    })
}

fn write_outputs(cli: &Cli, report: &Report) -> Result<(), Box<dyn Error>> {
    if let Some(path) = &cli.markdown_out {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, render_markdown(report))?;
    }

    if let Some(path) = &cli.json_out {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, serde_json::to_string_pretty(report)?)?;
    }

    Ok(())
}

fn print_console_report(report: &Report) {
    println!(
        "Calendar Conflict Scout | {} to {}",
        report.summary.range_start, report.summary.range_end
    );
    println!(
        "Calendars: {} | Events: {} | Conflicts: {} | Tight turnarounds: {} | Free windows: {}",
        report.summary.calendars_scanned,
        report.summary.total_events,
        report.summary.conflict_count,
        report.summary.tight_turnaround_count,
        report.summary.free_window_count
    );

    println!("\nConflicts");
    if report.conflicts.is_empty() {
        println!("  none");
    } else {
        for conflict in &report.conflicts {
            println!(
                "  {} {}-{} | {} <-> {}",
                conflict.start.date(),
                conflict.start.time().format("%H:%M"),
                conflict.end.time().format("%H:%M"),
                conflict.left.summary,
                conflict.right.summary
            );
        }
    }

    println!("\nTight turnarounds");
    if report.tight_turnarounds.is_empty() {
        println!("  none");
    } else {
        for turnaround in &report.tight_turnarounds {
            println!(
                "  {} minutes | {} -> {}",
                turnaround.gap_minutes, turnaround.earlier.summary, turnaround.later.summary
            );
        }
    }

    println!("\nBest free windows");
    let mut windows = report.free_windows.clone();
    windows.sort_by_key(|window| (-window.duration_minutes, window.start));
    if windows.is_empty() {
        println!("  none");
    } else {
        for window in windows.into_iter().take(5) {
            println!(
                "  {} {}-{} | {} minutes",
                window.day,
                window.start.time().format("%H:%M"),
                window.end.time().format("%H:%M"),
                window.duration_minutes
            );
        }
    }

    println!("\nBusy days");
    let mut busy_days = report.busy_days.clone();
    busy_days.sort_by_key(|day| (-day.busy_minutes, day.day));
    for day in busy_days.into_iter().take(5) {
        println!(
            "  {} | {} events | busy {} minutes | longest free window {} minutes",
            day.day, day.event_count, day.busy_minutes, day.longest_free_window_minutes
        );
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let cli = Cli::parse();
    let report = build_report(&cli)?;
    write_outputs(&cli, &report)?;
    print_console_report(&report);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_event(summary: &str, start: &str, end: &str) -> Event {
        Event {
            calendar: "sample".to_string(),
            summary: summary.to_string(),
            location: None,
            start: NaiveDateTime::parse_from_str(start, "%Y-%m-%d %H:%M:%S").unwrap(),
            end: NaiveDateTime::parse_from_str(end, "%Y-%m-%d %H:%M:%S").unwrap(),
            all_day: false,
        }
    }

    #[test]
    fn unfolds_folded_ics_lines() {
        let raw = "BEGIN:VEVENT\r\nSUMMARY:Operating Systems\r\n continued\r\nEND:VEVENT\r\n";
        let lines = unfold_ics_lines(raw);
        assert!(lines.contains(&"SUMMARY:Operating Systemscontinued".to_string()));
    }

    #[test]
    fn parses_basic_ics_event() {
        let temp_dir = std::env::temp_dir();
        let path = temp_dir.join(format!(
            "calendar-conflict-scout-{}-{}.ics",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::write(
            &path,
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20260701T090000\nDTEND:20260701T100000\nSUMMARY:Algorithms\nLOCATION:ECSS 2.102\nEND:VEVENT\nEND:VCALENDAR\n",
        )
        .unwrap();

        let events = parse_ics_events(&path).unwrap();
        fs::remove_file(path).unwrap();

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].summary, "Algorithms");
        assert_eq!(events[0].location.as_deref(), Some("ECSS 2.102"));
    }

    #[test]
    fn detects_conflicts_between_overlapping_events() {
        let events = vec![
            sample_event("Compilers", "2026-07-01 09:00:00", "2026-07-01 10:00:00"),
            sample_event("Advisor Meeting", "2026-07-01 09:30:00", "2026-07-01 10:15:00"),
        ];

        let conflicts = detect_conflicts(&events);
        assert_eq!(conflicts.len(), 1);
        assert_eq!(conflicts[0].start, events[1].start);
        assert_eq!(conflicts[0].end, events[0].end);
    }

    #[test]
    fn computes_free_windows_inside_day_bounds() {
        let events = vec![
            sample_event("Signals", "2026-07-01 09:00:00", "2026-07-01 10:00:00"),
            sample_event("Databases", "2026-07-01 12:00:00", "2026-07-01 13:30:00"),
        ];

        let windows = compute_free_windows(
            &events,
            NaiveDate::from_ymd_opt(2026, 7, 1).unwrap(),
            NaiveDate::from_ymd_opt(2026, 7, 1).unwrap(),
            NaiveTime::from_hms_opt(8, 0, 0).unwrap(),
            NaiveTime::from_hms_opt(18, 0, 0).unwrap(),
        );

        assert_eq!(windows[0].duration_minutes, 60);
        assert_eq!(windows[1].duration_minutes, 120);
        assert_eq!(windows[2].duration_minutes, 270);
    }

    #[test]
    fn summarizes_busy_days_from_events_and_free_windows() {
        let events = vec![
            sample_event("Signals", "2026-07-01 09:00:00", "2026-07-01 10:00:00"),
            sample_event("Databases", "2026-07-01 12:00:00", "2026-07-01 13:30:00"),
        ];

        let windows = compute_free_windows(
            &events,
            NaiveDate::from_ymd_opt(2026, 7, 1).unwrap(),
            NaiveDate::from_ymd_opt(2026, 7, 1).unwrap(),
            NaiveTime::from_hms_opt(8, 0, 0).unwrap(),
            NaiveTime::from_hms_opt(18, 0, 0).unwrap(),
        );
        let busy_days = summarize_busy_days(
            &events,
            &windows,
            NaiveDate::from_ymd_opt(2026, 7, 1).unwrap(),
            NaiveDate::from_ymd_opt(2026, 7, 1).unwrap(),
            NaiveTime::from_hms_opt(8, 0, 0).unwrap(),
            NaiveTime::from_hms_opt(18, 0, 0).unwrap(),
        );

        assert_eq!(busy_days.len(), 1);
        assert_eq!(busy_days[0].busy_minutes, 150);
        assert_eq!(busy_days[0].longest_free_window_minutes, 270);
    }
}
