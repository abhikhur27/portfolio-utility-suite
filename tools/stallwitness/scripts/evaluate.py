"""Run real Icarus RTL, then independently check protocol and accepted transactions."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stallwitness import read_vcd,analyze,compare,render_html
p=argparse.ArgumentParser();p.add_argument('--seeds',type=int,default=8);p.add_argument('--out',type=Path,default=ROOT/'build/evaluation');args=p.parse_args()
args.out.mkdir(parents=True,exist_ok=True);cases=[]
for mutation in range(4):
    binary=args.out/('fifo'+str(mutation))
    subprocess.run(['iverilog','-g2012','-s','tb','-Ptb.MUTATION='+str(mutation),'-o',str(binary),str(ROOT/'rtl/elastic_fifo.sv'),str(ROOT/'rtl/tb.sv')],check=True,capture_output=True)
    for seed in range(1,args.seeds+1):
        trace=args.out/f'm{mutation}-seed{seed}.vcd'
        subprocess.run(['vvp',str(binary),'+seed='+str(seed),'+vcd='+str(trace)],check=True,capture_output=True)
        result=analyze(read_vcd(trace.read_text(),'tb.clk','tb.out','tb.rst'))
        if mutation:
            ref=args.out/f'm0-seed{seed}.vcd'
            result['difference']=compare(result,analyze(read_vcd(ref.read_text(),'tb.clk','tb.out','tb.rst')))
        else:
            assert result['accepted']==list(range(96)),'Independent FIFO scoreboard mismatch'
        detected=bool(result['violations'] or result.get('difference'))
        assert detected==(mutation!=0),f'Unexpected checker result for mutation{mutation}/seed{seed}'
        cases.append({'mutation':mutation,'seed':seed,'detected':detected,'transfers':result['transfer_count'],'violations':len(result['violations'])})
        if seed==1:
            (args.out/f'm{mutation}.json').write_text(json.dumps(result,indent=2))
            (args.out/f'm{mutation}.html').write_text(render_html(result,f'FIFO mutation {mutation}'))
summary={'environment':'Icarus Verilog + Python; RTL simulation, not hardware','seeds':args.seeds,'cases':cases,
         'correct_cases':args.seeds,'mutant_cases_detected':sum(c['detected'] for c in cases),'independent_correct_fifo_scoreboard':True}
(args.out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
