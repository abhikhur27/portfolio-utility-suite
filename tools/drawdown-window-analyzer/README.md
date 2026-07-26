# Drawdown Window Analyzer

Practical C++ CLI for turning an equity-curve CSV into a concrete drawdown brief instead of a vague "it got choppy" claim.

## Why this exists

Portfolio PnL often looks fine until the underwater periods are measured honestly. This tool reads a dated value series and reports:

- worst peak-to-trough drawdown
- days from peak to trough so fast selloffs stand out separately from slow grind-down periods
- recovery lag after the trough so you can see how long the bounce-back actually took
- longest underwater stretch before recovery
- top drawdown windows ranked by severity
- average daily return and realized volatility
- optional Markdown and JSON reports for review handoff

It is intentionally simple: one CSV in, one risk brief out.

## Input CSV

Use a header row with:

- `date`
- `value`

Dates should be ISO-style (`YYYY-MM-DD`).

## Build

With Zig's C++ frontend:

```bash
zig c++ -std=c++17 -O2 main.cpp -o drawdown-window-analyzer.exe
```

## Usage

Run against the sample series:

```bash
drawdown-window-analyzer.exe --input samples/portfolio.csv --top 3
```

Export Markdown and JSON reports:

```bash
drawdown-window-analyzer.exe ^
  --input samples/portfolio.csv ^
  --top 5 ^
  --markdown-out reports/sample-report.md ^
  --json-out reports/sample-report.json
```

Run the built-in verification path:

```bash
drawdown-window-analyzer.exe --self-test
```

## Example output

```text
Drawdown Window Analyzer
Rows: 15 | Worst drawdown: -25.00% | Longest underwater: 9 days | Volatility: 3.05%
```

## Verification

```bash
zig c++ -std=c++17 -O2 main.cpp -o drawdown-window-analyzer.exe
drawdown-window-analyzer.exe --self-test
drawdown-window-analyzer.exe --input samples/portfolio.csv --top 3
```

## Portfolio positioning

- Project type: C++ command-line utility
- Direction fit: quant-risk workflow software instead of another browser demo
- Best demo move: run one equity curve and show the Markdown brief naming the worst drawdown window plus recovery lag
