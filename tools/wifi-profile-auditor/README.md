# WiFi Profile Auditor

Practical Rust CLI for auditing saved Windows Wi-Fi profiles, flagging insecure authentication choices, and surfacing which networks still auto-connect.

## Why this exists

Saved Wi-Fi profiles quietly pile up across dorms, apartments, campus labs, cafes, and travel. Months later, a laptop can still auto-join networks you no longer trust. This tool turns `netsh wlan` output into a short audit:

- which saved networks exist
- which authentication and cipher settings they use
- which profiles still connect automatically
- how many elevated/high-risk profiles still auto-connect
- which entries deserve cleanup first

It reads local profile metadata only. It does not change Wi-Fi settings.

## Usage

Basic console audit:

```bash
cargo run --release --
```

Write shareable artifacts:

```bash
cargo run --release -- --json-out reports/wifi-audit.json --markdown-out reports/wifi-audit.md
```

Show only the profiles worth reviewing first:

```bash
cargo run --release -- --min-risk 50
```

## Output

- Console summary with authentication breakdown and riskiest saved profiles
- Console summary also counts risky auto-connect profiles so cleanup starts with the profiles most likely to surprise you
- Optional JSON report for scripting or archival review
- Optional Markdown brief for cleanup or security review notes

## Verification

```bash
cargo fmt --check
cargo check
cargo run -- --markdown-out reports/self-check.md
```

## Portfolio Positioning

- Project type: Rust command-line Windows utility
- Direction fit: installable, non-browser workflow software
- Best demo: audit a laptop's saved Wi-Fi history and remove stale or risky profiles
