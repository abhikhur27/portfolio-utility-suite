"""Redistributable synthetic maintenance-dispatch example, not client data."""
def events():
    def record(eid, kind, entity, valid, known, payload):
        return dict(event_id=eid, kind=kind, entity=entity, valid_at=valid, known_at=known, payload=payload)
    r1 = dict(skills=['mechanical','electrical'],available=True,costs={'pump':2,'panel':4,'valve':1})
    r2 = dict(skills=['mechanical'],available=True,costs={'pump':3,'valve':2})
    return [
        record('crew-a','resource','crew-a',10,10,r1),
        record('crew-b','resource','crew-b',10,10,r2),
        record('pump','job','pump',10,10,dict(priority=6,skill='mechanical',deadline=10)),
        record('panel','job','panel',10,10,dict(priority=10,skill='electrical',deadline=10)),
        record('valve','job','valve',10,10,dict(priority=3,skill='mechanical',deadline=10)),
        record('late-outage','resource','crew-a',30,70,{**r1,'available':False}),
        record('late-priority','job','valve',20,80,dict(priority=8,skill='mechanical',deadline=10)),
        record('label-only','resource','crew-b',30,90,{**r2,'label':'Maintenance crew B'}),
    ]
