"""Public deterministic CLI; all input is local JSON and all output stays local."""
import argparse,json,sqlite3,sys,tempfile
from pathlib import Path
from . import append_events,read_events,explain,validated_events
from .report import render

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: '+key)
        result[key]=value
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description='Replay an operational decision before and after late facts arrive.')
    sub=parser.add_subparsers(dest='command',required=True)
    demo=sub.add_parser('demo',help='Run a labeled synthetic maintenance example')
    demo.add_argument('--out',type=Path,default=Path('build/demo'))
    replay=sub.add_parser('replay',help='Replay a local full-state event file')
    replay.add_argument('events',type=Path)
    for flag in ('valid-at','before','after'):
        replay.add_argument('--'+flag,type=int,required=True)
    replay.add_argument('--out',type=Path,required=True)
    replay.add_argument('--db',type=Path,help='Optional persistent append-only SQLite journal; existing facts are retained')
    args=parser.parse_args(argv)
    try:
        if args.command=='demo':
            from .demo import events
            data=events();valid_at,before,after=50,50,100
            provenance='Synthetic demonstration. No real dispatch or client data.'
        else:
            if args.events.stat().st_size>2_000_000:
                raise ValueError('Input exceeds the 2 MB limit')
            data=json.loads(args.events.read_text(encoding='utf-8'),object_pairs_hook=unique_object)
            valid_at,before,after=args.valid_at,args.before,args.after
            provenance='User-supplied events; provenance is not inferred.'
        data=validated_events(data)
        with tempfile.TemporaryDirectory(prefix='afterfact-') as temporary:
            database=getattr(args,'db',None) or Path(temporary)/'facts.sqlite'
            inserted=append_events(database,data)
            stored=read_events(database)
            result=explain(stored,valid_at,before,after)
        result['input_provenance']=provenance
        result['journal']={'events':len(stored),'newly_inserted':inserted,'persistent':getattr(args,'db',None) is not None}
        # Compute and validate everything before creating success artifacts.
        document=render(result)
        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/'report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        (args.out/'report.html').write_text(document,encoding='utf-8')
        if args.command=='demo':
            (args.out/'events.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'ok':True,'events':len(stored),'changed_facts':len(result['changed_facts']),
                          'witness_facts':len(result['witness']),'report':str(args.out/'report.html')}))
        return 0
    except (ValueError,TypeError,OSError,sqlite3.Error) as error:
        print('AfterFact: '+str(error),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
