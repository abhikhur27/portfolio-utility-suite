"""Generate and execute a small C reference/split classifier for differential replay."""
import ctypes,subprocess,tempfile
from pathlib import Path
def native_check(policy,plan,packets,cc='gcc'):
    from . import verify_plan
    if not verify_plan(policy,plan)['ok']:raise ValueError('Refusing native compilation of an unverified split')
    def table(name,items):
        records=[]
        for item in items:
            box=item['box'].ranges if hasattr(item['box'],'ranges') else item['box']
            records.append('{{'+','.join(str(lo)+'u' for lo,hi in box)+'},{'+','.join(str(hi)+'u' for lo,hi in box)+'},'+('1' if item['action']=='allow' else '0')+'}')
        return 'static const struct rule '+name+'[]={'+(','.join(records) or '{{0},{0},0}')+'};\n'
    c='#include <stdint.h>\nstruct rule {uint32_t lo[5],hi[5];int action;};\n'
    c+=table('original',policy['rules'])+table('offload',plan['rows'])
    c+='static int hit(const struct rule*r,const uint32_t*p){for(int i=0;i<5;i++)if(p[i]<r->lo[i]||p[i]>r->hi[i])return 0;return 1;}\n'
    default='1' if policy['default']=='allow' else '0'
    c+=f'int baseline(const uint32_t*p){{for(int i=0;i<{len(policy["rules"])};i++)if(hit(&original[i],p))return original[i].action;return {default};}}\n'
    c+=f'int split(const uint32_t*p){{for(int i=0;i<{len(plan["rows"])};i++)if(hit(&offload[i],p))return offload[i].action;return baseline(p);}}\n'
    with tempfile.TemporaryDirectory(prefix='rulesplit-') as tmp:
        source=Path(tmp)/'classifier.c';source.write_text(c);lib=Path(tmp)/'classifier.so'
        result=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-O2','-shared','-fPIC',str(source),'-o',str(lib)],capture_output=True,text=True,timeout=30)
        if result.returncode:raise ValueError('C classifier compilation failed: '+result.stderr[:500])
        dll=ctypes.CDLL(str(lib));arg=ctypes.POINTER(ctypes.c_uint32)
        for name in ('baseline','split'):getattr(dll,name).argtypes=[arg];getattr(dll,name).restype=ctypes.c_int
        for packet in packets:
            values=(ctypes.c_uint32*5)(*packet)
            expected=1 if __import__('rulesplit').classify(policy,packet)[0]=='allow' else 0
            if dll.baseline(values)!=expected or dll.split(values)!=expected:raise AssertionError('C/Python classification mismatch')
    return {'compiler':cc,'packets_compared':len(packets),'mismatches':0,'execution':'compiled C on host CPU, not DPU hardware'}
