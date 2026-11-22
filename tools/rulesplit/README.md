# RuleSplit

Moving a busy firewall rule onto an offload path sounds easy until it skips an earlier exception. RuleSplit finds that mistake and builds a checked alternative.

It takes an ordered IPv4 policy and a classic PCAP. The compiler subtracts earlier rules from later rules, breaks the remaining packet space into aligned prefix rows, and chooses full rule bundles within a row budget. An independent coverage check then verifies that each offload row agrees with the original first-match policy. Everything else still runs through the full CPU policy.

A rejected plan comes with a concrete five-tuple showing the changed decision. The demo also compiles and loads a C classifier, replaying the same capture through the Python reference, Python split and compiled C paths.

## Run it

Requirements: Python 3.10+; Linux and GCC for the optional native check. Python core has no third-party dependencies. Nothing sends packets or changes a machine's firewall.

```sh
git clone https://github.com/abhikhur27/portfolio-utility-suite.git
cd portfolio-utility-suite/tools/rulesplit
python3 -m unittest discover -s tests -v
python3 demo.py build/demo
python3 -m rulesplit examples/policy.json build/demo/traffic.pcap \
  --rows 8 --native-check --out build/plan.json
```

Open `build/demo/index.html`, inspect `build/plan.json`, or replay `build/demo/traffic.pcap` in your own tooling. The traffic is explicitly synthetic and redistributable. The CLI does not guess the provenance of a user-supplied capture.

The sample's first rule allows trusted API traffic. Its second rule drops other API traffic. Naively moving the second rule ahead of the first blocks trusted clients. The verifier constructs a TCP packet in that overlap. The checked split keeps its original answer.

## What the row budget means

Each abstract table row contains one aligned prefix for source IP, destination IP, source port, destination port and protocol. An arbitrary interval may need multiple prefixes; a rule's actual row cost is the Cartesian product of those covers. The compiler does not pretend every policy rule costs one row.

The selection heuristic is observed packet hits per row, with whole effective-rule bundles. It is **not an optimal knapsack solver**, does not partially install a bundle, and can leave rows unused. Packet-path counts are not CPU utilization, latency, throughput, or real DPU performance measurements.

## Why this exists

[P4's behavioral model](https://github.com/p4lang/behavioral-model) is a broader target for programmable data planes, and [DPDK](https://www.dpdk.org/) supplies production packet-processing building blocks. RuleSplit does not replace either. Its narrower job is to explain whether a proposed CPU/offload split preserves an ordered policy before target-specific integration. No existing portfolio project handles this exact packet-space and counterexample workflow.

## Supported model and boundaries

- Stateless IPv4 source/destination prefixes, TCP/UDP port ranges, protocol predicates, first-match `allow`/`drop`, and an explicit default. Other rule semantics and unknown JSON fields are rejected.
- The symbolic checker covers the specified integer five-tuple model exactly using interval intersections and subtraction. It returns a counterexample for a differing action. This is executable coverage reasoning, not an independently machine-checked formal proof.
- Classic Ethernet PCAP, including one VLAN tag and IPv4 header options. PCAP-NG, fragments, non-IPv4 and non-TCP/UDP captures fail explicitly. Unsupported real traffic must remain on a separately implemented CPU path; this repository does not install that path.
- Caps: 128 rules, 4,096 intermediate regions, 4,096 rows, one million parsed packets. A complexity-limited candidate remains on CPU. Invalid or truncated input stops the operation rather than guessing missing bytes.
- No stateful firewall, NAT, connection tracking, tunnels, real TCAM, SmartNIC driver, DPDK integration or physical DPU deployment. The generated C executes on the host CPU. Hardware-specific widths, priorities and capacities need a separate backend and validation.

Tests include exhaustive five-dimensional small-domain subtraction, randomized prefix covers, priority exceptions, shadowed rules, zero budgets, corrupted plans, capture round-trips and malformed captures. `examples/` contains actual checked output from the documented synthetic replay.

Independent, AI-assisted project by Abhimanyu Khurana. No Cisco affiliation or proprietary traffic. MIT licensed.
