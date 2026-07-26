# Correlation Regime Brief

Python CLI that turns a return-series CSV into a rolling-correlation brief around one anchor asset.

## Why this exists

Static correlation snapshots hide the exact thing risk workflows care about: when diversification stops working. This tool focuses on rolling relationship drift so you can quickly answer:

- Which assets are now moving with my anchor instead of offsetting it?
- Which pair just crossed a correlation threshold worth reviewing?
- Which hedge has actually stayed diversifying across the sampled window?

## Input format

Use a wide CSV with one date column and one return column per asset:

```csv
date,SPY,QQQ,TLT,GLD,XLE
2026-05-01,0.0042,0.0060,-0.0012,0.0018,0.0094
2026-05-02,-0.0035,-0.0051,0.0024,0.0007,-0.0072
```

- Return values can be decimals like `0.0042` or percentages like `0.42%`.
- Blank values are allowed, but the rolling window only advances when both assets in a pair have enough aligned observations.

## Usage

Basic brief:

```bash
python correlation_regime_brief.py --input sample_returns.csv --anchor SPY --window 10
```

Write shareable artifacts:

```bash
python correlation_regime_brief.py --input sample_returns.csv --anchor SPY --window 10 --pair-threshold 0.65 --markdown-out reports/correlation-brief.md --json-out reports/correlation-brief.json
```

## Output

The CLI prints:

- latest rolling correlation for each asset pair versus the anchor
- the minimum and maximum rolling correlation seen in the sample
- average absolute correlation across the windowed history
- sign-flip count and threshold-breach count
- a regime label that helps distinguish diversification, unstable drift, and high-coupling behavior

## Verification

```bash
python -m py_compile correlation_regime_brief.py
python correlation_regime_brief.py --input sample_returns.csv --anchor SPY --window 10 --markdown-out reports/sample.md --json-out reports/sample.json
```

## Portfolio Positioning

- Project type: Python command-line quant workflow utility
- Best use: sanity-check whether a hedge or diversifier is still behaving the way you expect
- Direction fit: practical standalone finance software with exportable review artifacts
