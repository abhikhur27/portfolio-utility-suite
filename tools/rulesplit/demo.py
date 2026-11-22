"""Create a redistributable synthetic PCAP and an independently checked split."""
import json,random,sys,html
from pathlib import Path
from rulesplit import load_policy,compile_plan,verify_plan,classify,split_classify
from rulesplit.pcap import encode_pcap,read_pcap
from rulesplit.native import native_check
root=Path(__file__).resolve().parent;out=Path(sys.argv[1]) if len(sys.argv)>1 else root/'build/demo';out.mkdir(parents=True,exist_ok=True)
data=json.loads((root/'examples/policy.json').read_text());policy=load_policy(data)
packets=[]
for count,src,dst,dport,proto in [(400,0xcb007100,0xac100001,443,6),(120,0x0a010100,0xac100001,443,6),(240,0xc6336400,0xc0000201,53,17),(120,0xcb007100,0xc0000201,22,6),(160,0xcb007100,0xc0000201,443,6),(40,0xcb007100,0xc0000201,80,6)]:
    packets.extend((src+(i%200),dst,1000+i,dport,proto) for i in range(count))
random.Random(27).shuffle(packets);capture=encode_pcap(packets);(out/'traffic.pcap').write_bytes(capture)
packets=read_pcap(capture);plan=compile_plan(policy,packets,8)
outcomes=[split_classify(policy,plan,p) for p in packets]
assert all(a[0]==classify(policy,p)[0] for a,p in zip(outcomes,packets))
naive={'rows':[{'box':policy['rules'][1]['box'].to_list(),'action':'drop','rule_id':'external-api'}]}
witness=verify_plan(policy,naive);assert not witness['ok']
report={'synthetic':True,'packet_count':len(packets),'offload_path_packets':sum(a[1]=='offload' for a in outcomes),
        'cpu_path_packets':sum(a[1]=='cpu' for a in outcomes),'mismatches':0,'rows':len(plan['rows']),
        'native_check':native_check(policy,plan,packets),'naive_counterexample':witness,'verification':plan['verification']}
(out/'plan.json').write_text(json.dumps(plan,indent=2));(out/'demo.json').write_text(json.dumps(report,indent=2))
escaped=html.escape(json.dumps(report,indent=2))
(out/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RuleSplit replay</title><style>body{background:#111110;color:#deded8;font:16px/1.65 monospace;max-width:900px;margin:48px auto;padding:0 22px}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#a7b89b}</style><h1>RuleSplit replay</h1><p>A hot drop rule overlaps an earlier allow rule. Moving it first would block trusted traffic. The checked split carves that overlap out before spending table rows.</p><p>All traffic here is synthetic. These are packet counts, not measured DPU throughput.</p><pre>'+escaped+'</pre></html>')
print(json.dumps(report))
