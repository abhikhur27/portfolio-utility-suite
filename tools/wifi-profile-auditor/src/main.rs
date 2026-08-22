use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::Path;
use std::process::Command;

#[derive(Debug, Clone)]
struct Options {
    json_out: Option<String>,
    markdown_out: Option<String>,
    min_risk: Option<u8>,
    capture_dir: Option<String>,
}

#[derive(Debug, Clone)]
struct WifiProfile {
    name: String,
    authentication: String,
    cipher: String,
    connection_mode: String,
    cost: String,
    security_key_present: String,
    risk_score: u8,
    risk_label: &'static str,
    recommendation: String,
}

#[derive(Debug, Clone)]
struct Report {
    input_mode: String,
    profile_count: usize,
    automatic_profile_count: usize,
    high_risk_automatic_profile_count: usize,
    authentication_breakdown: BTreeMap<String, usize>,
    profiles: Vec<WifiProfile>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Error: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let options = parse_args(env::args().skip(1).collect())?;
    let (mut profiles, input_mode) = if let Some(path) = options.capture_dir.as_deref() {
        (load_profiles_from_capture(path)?, "capture")
    } else {
        if !cfg!(target_os = "windows") {
            return Err(
                "Live Wi-Fi profile capture requires Windows; use --capture-dir for offline analysis."
                    .to_string(),
            );
        }
        (load_live_profiles()?, "live")
    };
    profiles.sort_by(|left, right| {
        right
            .risk_score
            .cmp(&left.risk_score)
            .then(left.name.cmp(&right.name))
    });

    let report = build_report(profiles, input_mode);
    print_console_summary(&report, &options);

    if let Some(path) = options.json_out.as_deref() {
        write_json(path, &report)?;
        println!("Wrote JSON report: {path}");
    }
    if let Some(path) = options.markdown_out.as_deref() {
        write_markdown(path, &report)?;
        println!("Wrote Markdown report: {path}");
    }
    Ok(())
}

fn parse_args(args: Vec<String>) -> Result<Options, String> {
    let mut options = Options {
        json_out: None,
        markdown_out: None,
        min_risk: None,
        capture_dir: None,
    };
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--json-out" => {
                index += 1;
                let value = args
                    .get(index)
                    .ok_or_else(|| "Missing value for --json-out".to_string())?;
                options.json_out = Some(value.clone());
            }
            "--markdown-out" => {
                index += 1;
                let value = args
                    .get(index)
                    .ok_or_else(|| "Missing value for --markdown-out".to_string())?;
                options.markdown_out = Some(value.clone());
            }
            "--min-risk" => {
                index += 1;
                let value = args
                    .get(index)
                    .ok_or_else(|| "Missing value for --min-risk".to_string())?;
                let parsed = value
                    .parse::<u8>()
                    .map_err(|_| format!("Invalid value for --min-risk: {value}"))?;
                if parsed > 100 {
                    return Err("--min-risk must be between 0 and 100".to_string());
                }
                options.min_risk = Some(parsed);
            }
            "--capture-dir" => {
                index += 1;
                let value = args
                    .get(index)
                    .ok_or_else(|| "Missing value for --capture-dir".to_string())?;
                options.capture_dir = Some(value.clone());
            }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            other => {
                return Err(format!("Unknown argument: {other}"));
            }
        }
        index += 1;
    }
    Ok(options)
}

fn print_usage() {
    println!(
        "WiFi Profile Auditor\n\
         Usage:\n\
           wifi-profile-auditor [--json-out path] [--markdown-out path] [--min-risk score] [--capture-dir path]\n\n\
         Examples:\n\
           wifi-profile-auditor\n\
           wifi-profile-auditor --json-out reports\\wifi.json --markdown-out reports\\wifi.md\n\
           wifi-profile-auditor --min-risk 50\n\
           wifi-profile-auditor --capture-dir fixtures/exposed-profiles"
    );
}

fn load_profile_names() -> Result<Vec<String>, String> {
    let output = run_netsh(&["wlan", "show", "profiles"])?;
    parse_profile_names(&output)
}

fn parse_profile_names(output: &str) -> Result<Vec<String>, String> {
    let mut names = Vec::new();
    for line in output.lines() {
        if let Some((key, value)) = split_kv_line(line) {
            let normalized = key.to_ascii_lowercase();
            if normalized.contains("all user profile") || normalized.contains("user profile") {
                let name = value.trim();
                if !name.is_empty() && !names.iter().any(|existing| existing == name) {
                    names.push(name.to_string());
                }
            }
        }
    }
    if names.is_empty() {
        return Err(
            "No saved Wi-Fi profiles found. `netsh wlan show profiles` returned no profile names."
                .to_string(),
        );
    }
    Ok(names)
}

fn load_live_profiles() -> Result<Vec<WifiProfile>, String> {
    let names = load_profile_names()?;
    let mut profiles = Vec::with_capacity(names.len());
    for name in names {
        profiles.push(load_profile(&name)?);
    }
    Ok(profiles)
}

fn load_profiles_from_capture(path: &str) -> Result<Vec<WifiProfile>, String> {
    let capture_dir = Path::new(path);
    let list_path = capture_dir.join("profile-list.txt");
    let list_output = fs::read_to_string(&list_path)
        .map_err(|error| format!("Unable to read {}: {error}", list_path.display()))?;
    let names = parse_profile_names(&list_output)?;
    let mut profiles = Vec::with_capacity(names.len());
    for name in names {
        let profile_path = capture_dir
            .join("profiles")
            .join(format!("{}.txt", capture_profile_slug(&name)));
        let output = fs::read_to_string(&profile_path)
            .map_err(|error| format!("Unable to read {}: {error}", profile_path.display()))?;
        profiles.push(parse_profile(&name, &output)?);
    }
    Ok(profiles)
}

fn capture_profile_slug(name: &str) -> String {
    let mut slug = String::new();
    let mut previous_separator = false;
    for character in name.chars() {
        if character.is_ascii_alphanumeric() {
            slug.push(character.to_ascii_lowercase());
            previous_separator = false;
        } else if !previous_separator && !slug.is_empty() {
            slug.push('_');
            previous_separator = true;
        }
    }
    slug.trim_matches('_').to_string()
}

fn load_profile(name: &str) -> Result<WifiProfile, String> {
    let output = run_netsh(&[
        "wlan",
        "show",
        "profiles",
        &format!("name={name}"),
        "key=clear",
    ])?;
    parse_profile(name, &output)
}

fn parse_profile(name: &str, output: &str) -> Result<WifiProfile, String> {
    let authentication = extract_field(output, &["Authentication", "Auth"])?
        .unwrap_or_else(|| "Unknown".to_string());
    let cipher = extract_field(output, &["Cipher"])?.unwrap_or_else(|| "Unknown".to_string());
    let connection_mode = extract_field(output, &["Connection mode", "Connection Mode"])?
        .unwrap_or_else(|| "Unknown".to_string());
    let cost =
        extract_field(output, &["Cost settings", "Cost"])?.unwrap_or_else(|| "Unknown".to_string());
    let security_key_present = extract_field(output, &["Security key", "Security key present"])?
        .unwrap_or_else(|| "Unknown".to_string());
    let (risk_score, risk_label, recommendation) = score_profile(
        &authentication,
        &cipher,
        &connection_mode,
        &cost,
        &security_key_present,
    );

    Ok(WifiProfile {
        name: name.to_string(),
        authentication,
        cipher,
        connection_mode,
        cost,
        security_key_present,
        risk_score,
        risk_label,
        recommendation,
    })
}

fn extract_field(output: &str, keys: &[&str]) -> Result<Option<String>, String> {
    for line in output.lines() {
        if let Some((key, value)) = split_kv_line(line) {
            let key_lower = key.to_ascii_lowercase();
            for wanted in keys {
                if key_lower == wanted.to_ascii_lowercase() {
                    return Ok(Some(value.trim().to_string()));
                }
            }
        }
    }
    Ok(None)
}

fn split_kv_line(line: &str) -> Option<(String, String)> {
    let trimmed = line.trim();
    let colon_index = trimmed.find(':')?;
    let key = trimmed[..colon_index].trim();
    let value = trimmed[colon_index + 1..].trim();
    if key.is_empty() {
        return None;
    }
    Some((key.to_string(), value.to_string()))
}

fn score_profile(
    authentication: &str,
    cipher: &str,
    connection_mode: &str,
    cost: &str,
    security_key_present: &str,
) -> (u8, &'static str, String) {
    let auth = authentication.to_ascii_lowercase();
    let cipher_lower = cipher.to_ascii_lowercase();
    let mode = connection_mode.to_ascii_lowercase();
    let cost_lower = cost.to_ascii_lowercase();
    let security_key = security_key_present.to_ascii_lowercase();

    let mut score = 15u8;
    let mut notes = Vec::new();

    if auth.contains("open") {
        score = score.saturating_add(55);
        notes.push("Open network profile detected");
    } else if auth.contains("wep") {
        score = score.saturating_add(45);
        notes.push("Legacy WEP authentication detected");
    } else if auth.contains("wpa3") {
        score = score.saturating_sub(5);
    } else if auth.contains("wpa2") {
        score = score.saturating_add(8);
    }

    if cipher_lower.contains("none") || cipher_lower.contains("wep") {
        score = score.saturating_add(18);
        notes.push("Weak or missing cipher");
    }
    if mode.contains("automatic") {
        score = score.saturating_add(10);
        notes.push("Connects automatically");
    }
    if cost_lower.contains("unrestricted") {
        score = score.saturating_add(4);
    }
    if security_key.contains("absent") || security_key.contains("not present") {
        score = score.saturating_add(8);
    }

    let (label, recommendation) = if score >= 75 {
        (
            "high",
            "Remove or reconfigure this saved profile unless you still explicitly trust the network.".to_string(),
        )
    } else if score >= 50 {
        (
            "elevated",
            "Review whether this profile should still auto-connect and whether the security settings are still acceptable.".to_string(),
        )
    } else if score >= 28 {
        (
            "moderate",
            "Keep only if you still use this network. Otherwise trim saved profiles to reduce accidental joins.".to_string(),
        )
    } else {
        (
            "low",
            "Profile looks routine. Keep it if the network is still in regular use.".to_string(),
        )
    };

    if !notes.is_empty() {
        return (
            score.min(100),
            label,
            format!("{recommendation} Signals: {}.", notes.join(", ")),
        );
    }
    (score.min(100), label, recommendation)
}

fn build_report(profiles: Vec<WifiProfile>, input_mode: &str) -> Report {
    let mut authentication_breakdown = BTreeMap::new();
    let automatic_profile_count = profiles
        .iter()
        .filter(|profile| {
            profile
                .connection_mode
                .eq_ignore_ascii_case("Connect automatically")
        })
        .count();
    let high_risk_automatic_profile_count = profiles
        .iter()
        .filter(|profile| {
            profile
                .connection_mode
                .eq_ignore_ascii_case("Connect automatically")
                && profile.risk_score >= 50
        })
        .count();
    for profile in &profiles {
        *authentication_breakdown
            .entry(profile.authentication.clone())
            .or_insert(0) += 1;
    }
    Report {
        input_mode: input_mode.to_string(),
        profile_count: profiles.len(),
        automatic_profile_count,
        high_risk_automatic_profile_count,
        authentication_breakdown,
        profiles,
    }
}

fn print_console_summary(report: &Report, options: &Options) {
    println!("WiFi Profile Auditor");
    println!("====================");
    println!("Input mode: {}", report.input_mode);
    println!("Saved profiles: {}", report.profile_count);
    println!("Auto-connect profiles: {}", report.automatic_profile_count);
    println!(
        "Auto-connect profiles at elevated/high risk: {}",
        report.high_risk_automatic_profile_count
    );
    if let Some(min_risk) = options.min_risk {
        println!("Minimum displayed risk score: {}", min_risk);
    }
    println!("Authentication mix:");
    for (authentication, count) in &report.authentication_breakdown {
        println!("  {:<24} {}", authentication, count);
    }
    println!();
    println!("Riskiest saved profiles:");
    for profile in report
        .profiles
        .iter()
        .filter(|profile| {
            options
                .min_risk
                .map(|minimum| profile.risk_score >= minimum)
                .unwrap_or(true)
        })
        .take(8)
    {
        println!(
            "  {:<28} {:>3}/100 {:<8} auth {:<18} mode {}",
            profile.name,
            profile.risk_score,
            profile.risk_label,
            profile.authentication,
            profile.connection_mode
        );
    }
}

fn write_json(path: &str, report: &Report) -> Result<(), String> {
    let mut lines = Vec::new();
    lines.push("{".to_string());
    lines.push(format!(
        "  \"input_mode\": \"{}\",",
        json_escape(&report.input_mode)
    ));
    lines.push(format!("  \"profile_count\": {},", report.profile_count));
    lines.push(format!(
        "  \"automatic_profile_count\": {},",
        report.automatic_profile_count
    ));
    lines.push(format!(
        "  \"high_risk_automatic_profile_count\": {},",
        report.high_risk_automatic_profile_count
    ));
    lines.push("  \"authentication_breakdown\": {".to_string());
    for (index, (authentication, count)) in report.authentication_breakdown.iter().enumerate() {
        let suffix = if index + 1 == report.authentication_breakdown.len() {
            ""
        } else {
            ","
        };
        lines.push(format!(
            "    \"{}\": {}{}",
            json_escape(authentication),
            count,
            suffix
        ));
    }
    lines.push("  },".to_string());
    lines.push("  \"profiles\": [".to_string());
    for (index, profile) in report.profiles.iter().enumerate() {
        let suffix = if index + 1 == report.profiles.len() {
            ""
        } else {
            ","
        };
        lines.push("    {".to_string());
        lines.push(format!(
            "      \"name\": \"{}\",",
            json_escape(&profile.name)
        ));
        lines.push(format!(
            "      \"authentication\": \"{}\",",
            json_escape(&profile.authentication)
        ));
        lines.push(format!(
            "      \"cipher\": \"{}\",",
            json_escape(&profile.cipher)
        ));
        lines.push(format!(
            "      \"connection_mode\": \"{}\",",
            json_escape(&profile.connection_mode)
        ));
        lines.push(format!(
            "      \"cost\": \"{}\",",
            json_escape(&profile.cost)
        ));
        lines.push(format!(
            "      \"security_key_present\": \"{}\",",
            json_escape(&profile.security_key_present)
        ));
        lines.push(format!("      \"risk_score\": {},", profile.risk_score));
        lines.push(format!("      \"risk_label\": \"{}\",", profile.risk_label));
        lines.push(format!(
            "      \"recommendation\": \"{}\"",
            json_escape(&profile.recommendation)
        ));
        lines.push(format!("    }}{suffix}"));
    }
    lines.push("  ]".to_string());
    lines.push("}".to_string());
    write_text_file(path, &lines.join("\n"))
}

fn write_markdown(path: &str, report: &Report) -> Result<(), String> {
    let mut lines = Vec::new();
    lines.push("# WiFi Profile Audit".to_string());
    lines.push(String::new());
    lines.push(format!("- Input mode: `{}`", report.input_mode));
    lines.push(format!("- Saved profiles: `{}`", report.profile_count));
    lines.push(format!(
        "- Auto-connect profiles: `{}`",
        report.automatic_profile_count
    ));
    lines.push(format!(
        "- Auto-connect profiles at elevated/high risk: `{}`",
        report.high_risk_automatic_profile_count
    ));
    lines.push(String::new());
    lines.push("## Authentication mix".to_string());
    for (authentication, count) in &report.authentication_breakdown {
        lines.push(format!("- `{authentication}`: `{count}`"));
    }
    lines.push(String::new());
    lines.push("## Profiles".to_string());
    for profile in &report.profiles {
        lines.push(format!("### {}", profile.name));
        lines.push(format!("- Authentication: `{}`", profile.authentication));
        lines.push(format!("- Cipher: `{}`", profile.cipher));
        lines.push(format!("- Connection mode: `{}`", profile.connection_mode));
        lines.push(format!("- Cost: `{}`", profile.cost));
        lines.push(format!(
            "- Security key present: `{}`",
            profile.security_key_present
        ));
        lines.push(format!(
            "- Risk: `{}` ({}/100)",
            profile.risk_label, profile.risk_score
        ));
        lines.push(format!("- Recommendation: {}", profile.recommendation));
        lines.push(String::new());
    }
    write_text_file(path, &lines.join("\n"))
}

fn write_text_file(path: &str, content: &str) -> Result<(), String> {
    let file_path = Path::new(path);
    if let Some(parent) = file_path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Unable to create {}: {error}", parent.display()))?;
        }
    }
    fs::write(file_path, content)
        .map_err(|error| format!("Unable to write {}: {error}", file_path.display()))
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

fn run_netsh(args: &[&str]) -> Result<String, String> {
    let output = Command::new("netsh")
        .args(args)
        .output()
        .map_err(|error| format!("Failed to launch netsh {:?}: {error}", args))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        return Err(format!(
            "netsh {:?} failed: {}\n{}{}",
            args,
            output.status,
            stdout.trim(),
            if stderr.trim().is_empty() {
                String::new()
            } else {
                format!("\n{}", stderr.trim())
            }
        ));
    }

    Ok(String::from_utf8_lossy(&output.stdout).into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captured_profiles_produce_stable_risk_posture() {
        let mut profiles = load_profiles_from_capture("fixtures/exposed-profiles").unwrap();
        profiles.sort_by(|left, right| {
            right
                .risk_score
                .cmp(&left.risk_score)
                .then(left.name.cmp(&right.name))
        });
        let report = build_report(profiles, "capture");

        assert_eq!(report.input_mode, "capture");
        assert_eq!(report.profile_count, 3);
        assert_eq!(report.automatic_profile_count, 2);
        assert_eq!(report.high_risk_automatic_profile_count, 2);
        assert_eq!(report.authentication_breakdown["Open"], 1);
        assert_eq!(report.authentication_breakdown["WEP"], 1);
        assert_eq!(report.authentication_breakdown["WPA3-Personal"], 1);
        assert_eq!(report.profiles[0].name, "Campus Guest");
        assert_eq!(report.profiles[0].risk_score, 100);
        assert_eq!(report.profiles[1].name, "Legacy Lab");
        assert_eq!(report.profiles[1].risk_score, 88);
        assert_eq!(report.profiles[2].name, "Home WPA3");
        assert_eq!(report.profiles[2].risk_score, 10);
    }

    #[test]
    fn capture_filename_slug_is_portable_and_stable() {
        assert_eq!(capture_profile_slug("Campus Guest"), "campus_guest");
        assert_eq!(capture_profile_slug("  Lab / WPA2  "), "lab_wpa2");
    }

    #[test]
    fn profile_list_parser_deduplicates_names() {
        let output = "All User Profile : Campus Guest\nUser Profile : Campus Guest\nAll User Profile : Home WPA3\n";
        assert_eq!(
            parse_profile_names(output).unwrap(),
            vec!["Campus Guest".to_string(), "Home WPA3".to_string()]
        );
    }
}
