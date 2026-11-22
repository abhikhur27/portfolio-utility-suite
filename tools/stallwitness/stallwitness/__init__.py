"""Ready/valid protocol and transaction checking from ordinary VCD files."""
from dataclasses import dataclass,asdict
import html,json,re

@dataclass(frozen=True)
class Sample:
    cycle:int
    time:int
    valid:int
    ready:int
    data:int|None
    reset:bool=False

def read_vcd(text,clock,interface,reset=None):
    if len(text)>32*1024*1024:raise ValueError('VCD exceeds the 32 MiB input limit')
    marker=re.search(r'\$enddefinitions\s+\$end',text)
    if not marker:raise ValueError('Missing VCD enddefinitions header')
    names={};scope=[];widths={}
    for command in re.findall(r'\$(?:scope|upscope|var)\b.*?\$end',text[:marker.end()],re.S):
        fields=command.split()
        if fields[0]=='$scope':scope.append(fields[2])
        elif fields[0]=='$upscope':
            if not scope:raise ValueError('Unbalanced VCD scope')
            scope.pop()
        else:
            if len(fields)<6:raise ValueError('Malformed VCD variable')
            width=int(fields[2]);code=fields[3];name='.'.join(scope+[fields[4]])
            if width<1 or width>4096:raise ValueError('Unsupported VCD signal width')
            if name in names:raise ValueError('Duplicate VCD signal name: '+name)
            names[name]=code;widths[name]=width
    wanted=[clock,interface+'_valid',interface+'_ready',interface+'_data']+([reset] if reset else [])
    for name in wanted:
        if name not in names:raise ValueError('Missing VCD signal: '+name)
    if any(widths[name]!=1 for name in wanted if name!=interface+'_data'):
        raise ValueError('Clock, valid, ready and reset must be single-bit')
    values={};pending=[];time=0;previous_time=-1;samples=[]
    def known(value):return value is not None and not re.search('[xz]',value,re.I)
    def flush():
        before=values.copy()
        for code,value in pending:values[code]=value
        if before.get(names[clock])!='0' or values.get(names[clock])!='1':return
        rst=before.get(names[reset]) if reset else '0'
        if not known(rst):raise ValueError('Unknown reset at time '+str(time))
        if rst=='1':samples.append(Sample(len(samples),time,0,0,None,True));return
        v=before.get(names[interface+'_valid']);r=before.get(names[interface+'_ready'])
        if not known(v):raise ValueError('unknown valid at time '+str(time))
        if v=='1' and not known(r):raise ValueError('Unknown active ready at time '+str(time))
        data=before.get(names[interface+'_data'])
        samples.append(Sample(len(samples),time,int(v,2),int(r,2) if known(r) else 0,int(data,2) if known(data) else None))
    for raw in text[marker.end():].splitlines():
        line=raw.strip()
        if not line or line.startswith('$'):continue
        if re.fullmatch(r'#\d+',line):
            flush();pending=[];previous_time=time;time=int(line[1:])
            if time<previous_time:raise ValueError('VCD timestamps move backwards')
        elif line[0].lower() in '01xz':pending.append((line[1:],line[0].lower()))
        elif line[0].lower()=='b':
            parts=line[1:].split()
            if len(parts)!=2 or not re.fullmatch('[01xzXZ]+',parts[0]):raise ValueError('Malformed VCD vector')
            pending.append((parts[1],parts[0].lower()))
        elif line[0].lower()=='r':continue
        else:raise ValueError('Unsupported VCD change: '+line[:30])
    flush()
    if not samples:raise ValueError('No rising clock edges were sampled')
    return samples

def analyze(samples):
    violations=[];accepted=[];transfers=[];prior=None;stall=0;longest=0
    for sample in samples:
        if sample.reset:prior=None;stall=0;continue
        def problem(kind,**extra):
            violations.append({'kind':kind,'cycle':sample.cycle,'time':sample.time,**extra,
                'witness':[asdict(x) for x in samples[max(0,sample.cycle-4):sample.cycle+2]]})
        if sample.valid and sample.data is None:problem('unknown_active_data')
        if prior and prior.valid and not prior.ready:
            if not sample.valid:problem('valid_withdrawn',previous_cycle=prior.cycle)
            elif sample.data!=prior.data:problem('data_changed_while_stalled',previous_data=prior.data,current_data=sample.data)
        if sample.valid and sample.ready:
            accepted.append(sample.data);transfers.append({'cycle':sample.cycle,'time':sample.time,'data':sample.data})
        stall=stall+1 if sample.valid and not sample.ready else 0
        longest=max(longest,stall);prior=sample
    return {'schema':1,'sample_count':len(samples),'transfer_count':len(accepted),'accepted':accepted,
            'transfers':transfers,'stall_cycles':sum(bool(s.valid and not s.ready and not s.reset) for s in samples),
            'longest_stall':longest,'violations':violations}

def compare(actual,reference):
    left=actual['accepted'];right=reference['accepted']
    for i in range(max(len(left),len(right))):
        a=left[i] if i<len(left) else None;b=right[i] if i<len(right) else None
        if i>=len(left) or i>=len(right) or a!=b:
            return {'kind':'missing_transfer' if i>=len(left) else 'extra_transfer' if i>=len(right) else 'different_transfer',
                    'index':i,'actual':a,'expected':b,'actual_transfer':actual['transfers'][i] if i<len(left) else None,
                    'reference_transfer':reference['transfers'][i] if i<len(right) else None}
    return None

def render_html(result,title='StallWitness'):
    esc=lambda x:html.escape(str(x))
    failures=result.get('violations',[])
    rows=[]
    for failure in failures[:3]:
        trace=''.join('<tr>'+''.join('<td>'+esc(s[k])+'</td>' for k in ('cycle','time','valid','ready','data'))+'</tr>' for s in failure['witness'])
        rows.append('<section><h2>'+esc(failure['kind'])+' at cycle '+esc(failure['cycle'])+'</h2><table><thead><tr><th>Cycle</th><th>Time</th><th>Valid</th><th>Ready</th><th>Data</th></tr></thead><tbody>'+trace+'</tbody></table></section>')
    diff=result.get('difference')
    if diff:rows.insert(0,'<section><h2>First transfer difference</h2><pre>'+esc(json.dumps(diff,indent=2))+'</pre></section>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>body{background:#111110;color:#deded8;font:16px/1.65 monospace;max-width:900px;margin:50px auto;padding:0 22px}h1,h2{font-weight:500}h2{font-size:18px}section{border-top:1px solid #444;padding:15px 0}td,th{padding:4px 18px;text-align:left}pre{overflow:auto}a{color:#a7b89b}</style><h1>'+esc(title)+'</h1><p>'+esc(result['transfer_count'])+' transfers. '+esc(result['stall_cycles'])+' stalled cycles. '+esc(len(failures))+' protocol violations.</p><p>Samples are taken immediately before the rising edge. Transfer comparison ignores latency, not data or order.</p>'+''.join(rows or ['<p>No protocol violation or transfer difference found.</p>'])+'</html>'
