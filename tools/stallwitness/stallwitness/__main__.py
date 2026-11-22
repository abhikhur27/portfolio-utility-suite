import argparse,json,sys
from pathlib import Path
from . import read_vcd,analyze,compare,render_html

def main():
    p=argparse.ArgumentParser(description='Check a ready/valid interface from a VCD and write a short witness.')
    p.add_argument('vcd',type=Path);p.add_argument('--clock',default='tb.clk');p.add_argument('--interface',default='tb.out')
    p.add_argument('--reset',default='tb.rst');p.add_argument('--reference',type=Path);p.add_argument('--out',type=Path,default=Path('build/report'))
    args=p.parse_args()
    try:
        result=analyze(read_vcd(args.vcd.read_text(),args.clock,args.interface,args.reset or None))
        if args.reference:result['difference']=compare(result,analyze(read_vcd(args.reference.read_text(),args.clock,args.interface,args.reset or None)))
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        args.out.with_suffix('.html').write_text(render_html(result,args.vcd.name),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('accepted','transfers','violations')}|{'violations':len(result['violations'])}))
        return 1 if result['violations'] or result.get('difference') else 0
    except (OSError,ValueError) as error:p.exit(2,'stallwitness: '+str(error)+'\n')
if __name__=='__main__':sys.exit(main())
