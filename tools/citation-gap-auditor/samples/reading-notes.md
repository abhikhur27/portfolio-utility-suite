# Efficient Transformers

## Core claim

Sparse attention reduces memory growth enough to make longer context windows practical on commodity GPUs.

The paper reports a 28 percent memory reduction at the tested sequence length without materially hurting perplexity [12].

## Limitations

The evaluation only covers two translation datasets and does not test retrieval-heavy downstream tasks.

## Follow-up

- Re-check whether the ablation table explains which sparsity pattern dominates latency.
- Compare the reported throughput figures against the baseline appendix before reusing the performance claim.
