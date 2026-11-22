"""Exact packet-space carving for first-match IPv4 ACLs. No DPU is required."""
from dataclasses import dataclass
import ipaddress,itertools,math
BITS=(32,32,16,16,8)
LIMITS=tuple((0,(1<<n)-1) for n in BITS)

def representative(box):
    packet=[r[0] for r in box.ranges]
    lo,hi=box.ranges[-1]
    if lo<=6<=hi:packet[-1]=6
    elif lo<=17<=hi:packet[-1]=17
    return packet

@dataclass(frozen=True)
class Box:
    ranges:tuple
    def __post_init__(self):
        if len(self.ranges)!=5 or any(len(r)!=2 or not all(isinstance(v,int) and not isinstance(v,bool) for v in r) or r[0]>r[1] for r in self.ranges):raise ValueError('A box needs five inclusive integer ranges')
    def contains(self,packet):return all(a<=x<=b for (a,b),x in zip(self.ranges,packet)) and len(packet)==5
    def to_list(self):return [list(x) for x in self.ranges]

def intersection(a,b):
    ranges=tuple((max(x[0],y[0]),min(x[1],y[1])) for x,y in zip(a.ranges,b.ranges))
    return None if any(l>h for l,h in ranges) else Box(ranges)

def subtract(a,b):
    common=intersection(a,b)
    if common is None:return [a]
    remaining=list(a.ranges);pieces=[]
    for axis,(lo,hi) in enumerate(common.ranges):
        left,right=remaining[axis]
        if left<lo:
            part=remaining.copy();part[axis]=(left,lo-1);pieces.append(Box(tuple(part)))
        if right>hi:
            part=remaining.copy();part[axis]=(hi+1,right);pieces.append(Box(tuple(part)))
        remaining[axis]=(lo,hi)
    return pieces

def prefixes(lo,hi,bits):
    if not 0<=lo<=hi<(1<<bits):raise ValueError('Range is outside the field width')
    out=[]
    while lo<=hi:
        block=(lo & -lo) if lo else (1<<bits)
        while block>hi-lo+1:block//=2
        out.append((lo,lo+block-1));lo+=block
    return out

def port(value):
    bounds=(value,value) if isinstance(value,int) and not isinstance(value,bool) else tuple(value) if isinstance(value,list) else None
    if bounds is None or len(bounds)!=2 or not all(isinstance(v,int) and not isinstance(v,bool) for v in bounds) or not 0<=bounds[0]<=bounds[1]<=65535:raise ValueError('Port must be an integer or an inclusive [low, high] range')
    return bounds

def load_policy(data):
    if set(data)-{'default','rules'}:raise ValueError('Unknown policy field')
    if data.get('default') not in {'allow','drop'}:raise ValueError('Default must be allow or drop')
    rules=data.get('rules')
    if not isinstance(rules,list) or len(rules)>128:raise ValueError('At most 128 ordered rules are supported')
    result=[];seen=set()
    for raw in rules:
        if set(raw)-{'id','action','src','dst','sport','dport','proto'}:raise ValueError('Unknown rule field')
        name=raw.get('id');action=raw.get('action')
        if not isinstance(name,str) or not name or name in seen or len(name)>100:raise ValueError('Rule IDs must be unique nonempty strings')
        if action not in {'allow','drop'}:raise ValueError('Action must be allow or drop')
        seen.add(name);bounds=[]
        for key in ('src','dst'):
            net=ipaddress.ip_network(raw.get(key,'0.0.0.0/0'),strict=False)
            if net.version!=4:raise ValueError('Only IPv4 is supported')
            bounds.append((int(net.network_address),int(net.broadcast_address)))
        bounds.extend([port(raw.get('sport',[0,65535])),port(raw.get('dport',[0,65535]))])
        protocol=raw.get('proto','any')
        if protocol not in {'any','tcp','udp'}:raise ValueError('Protocol must be any, tcp or udp')
        bounds.append((0,255) if protocol=='any' else (6,6) if protocol=='tcp' else (17,17))
        result.append({'id':name,'action':action,'box':Box(tuple(bounds))})
    return {'default':data['default'],'rules':result}

def classify(policy,packet):
    for rule in policy['rules']:
        if rule['box'].contains(packet):return rule['action'],rule['id']
    return policy['default'],'default'

def split_classify(policy,plan,packet):
    for row in plan['rows']:
        if Box(tuple(tuple(x) for x in row['box'])).contains(packet):return row['action'],'offload'
    return classify(policy,packet)[0],'cpu'

def effective_regions(policy,index,max_regions=4096):
    regions=[policy['rules'][index]['box']]
    for previous in policy['rules'][:index]:
        regions=[piece for region in regions for piece in subtract(region,previous['box'])]
        if len(regions)>max_regions:raise ValueError('Packet-space region limit exceeded; keep this rule on CPU')
    return regions

def compile_plan(policy,packets,row_budget):
    if not isinstance(row_budget,int) or not 0<=row_budget<=4096:raise ValueError('Row budget must be 0 through 4096')
    weights={r['id']:0 for r in policy['rules']}
    for packet in packets:
        _,rid=classify(policy,packet)
        if rid in weights:weights[rid]+=1
    candidates=[];skipped=[]
    for index,rule in enumerate(policy['rules']):
        try:
            regions=effective_regions(policy,index)
            shapes=[[prefixes(lo,hi,bits) for (lo,hi),bits in zip(b.ranges,BITS)] for b in regions]
            cost=sum(math.prod(len(p) for p in dimensions) for dimensions in shapes)
            candidates.append((index,rule,shapes,cost))
        except ValueError as e:skipped.append({'rule_id':rule['id'],'reason':str(e)})
    candidates.sort(key=lambda c:(-weights[c[1]['id']]/max(c[3],1),c[0]))
    rows=[];selected=[]
    for index,rule,shapes,cost in candidates:
        if not cost or not weights[rule['id']]:continue
        if len(rows)+cost>row_budget:
            skipped.append({'rule_id':rule['id'],'reason':'row_budget','required_rows':cost});continue
        for dimensions in shapes:
            rows.extend({'box':[list(x) for x in p],'action':rule['action'],'rule_id':rule['id']} for p in itertools.product(*dimensions))
        selected.append({'rule_id':rule['id'],'rows':cost,'observed_packets':weights[rule['id']]})
    plan={'schema':1,'row_budget':row_budget,'rows':rows,'selected':selected,'skipped':skipped,
          'selection':'greedy observed hits per prefix row; not an optimality claim','target':'abstract stateless IPv4 prefix table; no physical DPU execution'}
    verdict=verify_plan(policy,plan)
    if not verdict['ok']:raise AssertionError('Compiler emitted an unsafe plan')
    plan['verification']=verdict
    return plan

def verify_plan(policy,plan):
    rows=plan.get('rows')
    if not isinstance(rows,list) or len(rows)>4096:raise ValueError('Invalid offload table')
    if 'row_budget' in plan and len(rows)>plan['row_budget']:raise ValueError('Plan exceeds its row budget')
    boxes=[]
    for row in rows:
        if row.get('action') not in {'allow','drop'}:raise ValueError('Invalid offload action')
        box=Box(tuple(tuple(x) for x in row['box']))
        if any(lo<0 or hi>(1<<bits)-1 for (lo,hi),bits in zip(box.ranges,BITS)):raise ValueError('Offload field outside its domain')
        # Every published row is one aligned ternary prefix per field.
        if any(len(prefixes(lo,hi,bits))!=1 for (lo,hi),bits in zip(box.ranges,BITS)):raise ValueError('Offload rows must be aligned prefixes')
        if any(intersection(box,old) is not None for old in boxes):raise ValueError('Offload rows overlap')
        boxes.append(box);uncovered=[box]
        for rule in policy['rules']:
            next_parts=[]
            for piece in uncovered:
                hit=intersection(piece,rule['box'])
                if hit is not None and rule['action']!=row['action']:
                    return {'ok':False,'packet':representative(hit),'policy_action':rule['action'],'offload_action':row['action'],'matched_rule':rule['id']}
                next_parts.extend(subtract(piece,rule['box']))
            uncovered=next_parts
            if len(uncovered)>4096:raise ValueError('Verification region limit exceeded')
            if not uncovered:break
        if uncovered and row['action']!=policy['default']:
            return {'ok':False,'packet':representative(uncovered[0]),'policy_action':policy['default'],'offload_action':row['action'],'matched_rule':'default'}
    return {'ok':True,'rows_checked':len(rows),'method':'exact integer packet-space coverage; CPU fallback retains the full ordered policy'}
