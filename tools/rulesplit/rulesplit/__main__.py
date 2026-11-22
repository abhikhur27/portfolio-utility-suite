import argparse,json,sys
from pathlib import Path
from . import load_policy,compile_plan,verify_plan,classify,split_classify
from .pcap import read_pcap
from .native import native_check
def main():
    p=argparse.ArgumentParser(description='Plan a semantics-preserving ACL split from an ordered policy and a classic PCAP.')
    p.add_argument('policy',type=Path);p.add_argument('pcap',type=Path);p.add_argument('--rows',type=int,default=8)
    p.add_argument('--out',type=Path,default=Path('build/plan.json'));p.add_argument('--native-check',action='store_true')
    args=p.parse_args()
    try:
        policy=load_policy(json.loads(args.policy.read_text()));packets=read_pcap(args.pcap.read_bytes())
        plan=compile_plan(policy,packets,args.rows)
        outcomes=[split_classify(policy,plan,x) for x in packets]
        mismatches=sum(a[0]!=classify(policy,x)[0] for a,x in zip(outcomes,packets))
        assert not mismatches
        report={'input_provenance':'user-supplied capture; provenance not inferred','captured_packets':len(packets),'offload_path_packets':sum(x[1]=='offload' for x in outcomes),'cpu_path_packets':sum(x[1]=='cpu' for x in outcomes),'mismatches':mismatches}
        if args.native_check:report['native_check']=native_check(policy,plan,packets)
        plan['replay']=report;args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(plan,indent=2))
        print(json.dumps({'rows':len(plan['rows']),'verification':plan['verification'],'replay':report}));return 0
    except (OSError,ValueError,KeyError,TypeError) as e:p.exit(2,'rulesplit: '+str(e)+'\n')
if __name__=='__main__':sys.exit(main())
