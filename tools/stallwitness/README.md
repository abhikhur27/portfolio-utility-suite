# StallWitness

Find the few clock edges that explain a ready/valid failure, without opening a giant waveform first.

Give it an ordinary VCD, the clock name, and an interface prefix. It checks that a producer holds its data and valid signal while the consumer is stalled. It can also compare the **accepted transaction sequence** against a reference run, even when their latency differs. The output is JSON plus a small, offline HTML witness with the surrounding clock edges.

The included SystemVerilog FIFO and seeded testbench are real RTL. The Python checker is separate from the RTL: the correct FIFO must also pass an independent `0..95` transaction scoreboard. Three injected defects cover changing stalled data, popping without ready, and a stuck read pointer.

## Run it

Requirements: Python 3.10+, Icarus Verilog (`iverilog` and `vvp`). No Python runtime dependencies.

```sh
git clone https://github.com/abhikhur27/portfolio-utility-suite.git
cd portfolio-utility-suite/tools/stallwitness
python3 -m unittest discover -s tests -v
python3 scripts/evaluate.py --seeds 8 --out build/evaluation
python3 -m stallwitness build/evaluation/m1-seed1.vcd \
  --reference build/evaluation/m0-seed1.vcd --out build/witness
# Exit 1 is expected: the injected failure was detected.
```

Open `build/witness.html`. Exit codes: `0` means no difference found, `1` means a protocol or transaction failure, `2` means an invalid input or missing signal. The eight-seed evaluation runs 32 RTL cases: eight correct cases and 24 faulty cases. Its assertions fail if any correct run is flagged, any injected fault escapes, or the independent correct-FIFO scoreboard disagrees.

For an existing trace:

```sh
python3 -m stallwitness trace.vcd --clock top.clk \
  --interface top.output --reset top.reset --out build/output-check
```

The prefix resolves `top.output_valid`, `top.output_ready`, and `top.output_data`. Pass `--reset ''` for a trace without reset. Signals must be named exactly; missing or ambiguous configuration is not guessed. JSON contains raw VCD time ticks, cycle numbers, accepted transfers, stalls, and short failure windows. `examples/` includes actual generated results from the checked RTL run, not a hand-drawn trace.

## Why another waveform tool?

[GTKWave](https://github.com/gtkwave/gtkwave) is the right tool for freely inspecting waveforms. Assertions and tools such as [cocotb](https://www.cocotb.org/) are better when a live testbench is available. StallWitness sits after the run: it can check an already-saved VCD, collapse a long trace to a local witness, and compare transaction order without requiring cycle-for-cycle alignment. It is deliberately not a replacement for those tools.

## Sampling and limits

- Samples use the values **before** the rising-edge timestamp group, rather than post-NBA register values. This avoids blaming a correct FIFO for changing its output after a transfer. The parser's pre-edge regression test covers this distinction.
- Valid must remain asserted, and data must remain stable, from a stalled edge through its accepting edge. Unknown active data is reported. Unknown valid/ready/reset controls fail the input check instead of silently becoming zero.
- Reset is synchronous, active-high, and clears the previous hold expectation. Differential comparison spans the complete capture; use traces with equivalent reset boundaries.
- Supports ordinary binary/scalar VCD and plain hierarchical names, up to 32 MiB. It does not implement the complete VCD standard, FST, every AXI sideband, asynchronous-clock crossing checks, or formal liveness.
- It checks one ready/valid data channel. It cannot establish AXI compliance, prove deadlock freedom, or infer whether latency is acceptable. A trace with no transactions is not evidence of a working circuit.
- The witness is a bounded local window, not a claim of globally minimal causal reduction. Comparison requires equivalent input transactions in the two runs.
- The FIFO is a four-entry, power-of-two teaching design. No synthesis, timing closure, FPGA board, or fabricated silicon result is claimed.

Independent, AI-assisted project by Abhimanyu Khurana. No Cisco affiliation or proprietary designs. MIT licensed.
