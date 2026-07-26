# Dataset Split Auditor

Java CLI that audits train/test/validation CSV splits for practical leakage problems before model training or publication.

It checks:

- exact row overlap across splits
- duplicate `id` values across and within splits
- temporal leakage when train dates run into test dates
- nonblank date strings that fail parsing before temporal checks
- label skew by split so evaluation posture is visible early
- missing core-field counts for `id`, `date`, and `label`
- label values that appear in one split but disappear in another

## Why it exists

Split bugs are easy to miss and expensive to defend later. This tool gives one quick pass that answers whether a dataset split looks publishable or already contains leakage risk.

## Usage

Compile:

```bash
javac src/DatasetSplitAuditor.java
```

Run:

```bash
java -cp src DatasetSplitAuditor --train examples/train.csv --test examples/test.csv --validation examples/validation.csv --report-out reports/sample-audit.md --json-out reports/sample-audit.json
```

Optional columns default to `id`, `date`, and `label`, but you can override them:

```bash
java -cp src DatasetSplitAuditor --train train.csv --test test.csv --id-column sample_id --date-column trade_date --label-column regime
```

## Output

- console warning summary
- Markdown audit brief
- JSON audit payload for downstream checks or CI hooks
- split-level invalid date counts so malformed time fields do not silently bypass the leakage audit

## Example findings

The bundled sample files intentionally trigger:

- one exact train/test row overlap
- one shared `id` between train and validation
- a train/test date-order problem

## Portfolio Positioning

- Project type: Java command-line ML workflow utility
- Best use: validate dataset splits before training results get presented as real evidence

## Verification

```bash
javac src/DatasetSplitAuditor.java
java -cp src DatasetSplitAuditor --train examples/train.csv --test examples/test.csv --validation examples/validation.csv --report-out reports/sample-audit.md --json-out reports/sample-audit.json
```
