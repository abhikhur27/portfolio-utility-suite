import itertools,json,random,tempfile,unittest
from pathlib import Path
import afterfact as a

def event(eid,kind,entity,valid,known,payload):
 return dict(event_id=eid,kind=kind,entity=entity,valid_at=valid,known_at=known,payload=payload)
def resource(skills=('mechanical',),available=True,costs=None):
 return dict(skills=list(skills),available=available,costs=costs or {})
def job(priority=1,skill='mechanical',deadline=20):
 return dict(priority=priority,skill=skill,deadline=deadline)
def state(*events):return {e['kind']+'/'+e['entity']:e for e in events}

class TemporalTests(unittest.TestCase):
 def test_late_correction_does_not_leak_into_past_knowledge(self):
  x=event('a','job','x',10,10,job(1));y=event('b','job','x',10,80,job(8))
  self.assertEqual(a.snapshot([y,x],50,50),{'job/x':x})
  self.assertEqual(a.snapshot([x,y],50,90),{'job/x':y})
 def test_newer_effective_state_beats_late_older_state(self):
  x=event('a','job','x',30,30,job(4));y=event('b','job','x',10,80,job(8))
  self.assertEqual(a.snapshot([y,x],50,90),{'job/x':x})
 def test_future_effective_record_is_excluded(self):
  x=event('a','job','x',100,10,job())
  self.assertEqual(a.snapshot([x],50,50),{})
 def test_invalid_bool_timestamp_is_rejected(self):
  with self.assertRaises(ValueError):a.snapshot([event('a','job','x',True,1,job())],5,5)

class AllocationTests(unittest.TestCase):
 def test_global_matching_beats_greedy_nearest_assignment(self):
  s=state(event('a','resource','flex',0,0,resource(('mechanical','electrical'),costs={'pump':1,'panel':2})),event('b','resource','mech',0,0,resource(costs={'pump':3})),event('c','job','panel',0,0,job(10,'electrical')),event('d','job','pump',0,0,job(6)))
  self.assertEqual(a.allocate(s),{'assignments':{'panel':'flex','pump':'mech'},'unassigned':[],'covered_priority':16,'travel_cost':5})
 def test_skills_deadlines_and_unavailability_are_hard_constraints(self):
  s=state(event('a','resource','r',0,0,resource(costs={'j':5})),event('b','job','j',0,0,job(10,deadline=4)))
  self.assertEqual(a.allocate(s).get('assignments'),{})
  self.assertEqual(a.allocate(s).get('unassigned'),['j'])
 def test_no_resource_can_be_used_twice(self):
  s=state(event('a','resource','r',0,0,resource(costs={'x':1,'y':1})),event('b','job','x',0,0,job(4)),event('c','job','y',0,0,job(9)))
  self.assertEqual(a.allocate(s).get('assignments'),{'y':'r'})

class JournalTests(unittest.TestCase):
 def test_reopen_and_idempotent_ingestion(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'journal.sqlite';x=event('a','job','x',1,1,job())
   self.assertEqual(a.append_events(p,[x]),1)
   self.assertEqual(a.append_events(p,[x]),0)
   self.assertEqual(a.read_events(p),[x])

if __name__=='__main__':unittest.main()
