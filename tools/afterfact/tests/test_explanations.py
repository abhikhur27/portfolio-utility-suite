import copy,itertools,json,random,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
import afterfact as a
from afterfact.demo import events
from test_afterfact import event,resource,job,state

class ExplanationTests(unittest.TestCase):
 def test_reduces_three_changed_facts_to_two_necessary_corrections(self):
  r=a.explain(events(),50,50,100)
  self.assertEqual(r['before']['assignments'],{'panel':'crew-a','pump':'crew-b'})
  self.assertEqual(r['after']['assignments'],{'valve':'crew-b'})
  self.assertEqual(r['changed_facts'],['job/valve','resource/crew-a','resource/crew-b'])
  self.assertEqual([x['key'] for x in r['witness']],['job/valve','resource/crew-a'])
 def test_each_retained_fact_is_necessary_within_the_witness(self):
  r=a.explain(events(),50,50,100);base=a.snapshot(events(),50,50)
  for removed in r['witness']:
   patched=copy.deepcopy(base)
   for item in r['witness']:
    if item['key']!=removed['key']:patched[item['key']]=item['after']
   self.assertNotEqual(a.allocate(patched),r['after'])
 def test_source_arrival_order_does_not_change_the_report(self):
  data=events();r=a.explain(data,50,50,100);random.Random(8).shuffle(data)
  self.assertEqual(a.explain(data,50,50,100),r)
 def test_unchanged_decision_has_empty_witness(self):
  self.assertEqual(a.explain(events(),50,50,60)['witness'],[])
 def test_tombstone_removes_an_active_job(self):
  data=events()+[event('deleted','job','panel',40,45,None)]
  self.assertNotIn('panel',a.explain(data,50,30,50)['after']['unassigned'])
  self.assertNotIn('panel',a.explain(data,50,30,50)['after']['assignments'])
 def test_reversed_knowledge_cutoffs_rejected(self):
  with self.assertRaises(ValueError):a.explain(events(),50,100,50)

class PersistenceTests(unittest.TestCase):
 def test_conflict_rolls_back_new_records_in_the_same_batch(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'facts.sqlite';x=event('a','job','x',1,1,job())
   a.append_events(p,[x])
   with self.assertRaises(ValueError):a.append_events(p,[event('b','job','y',1,1,job()),{**x,'payload':job(9)}])
   self.assertEqual(a.read_events(p),[x])
 def test_conflicting_ids_inside_one_batch_are_rejected(self):
  x=event('a','job','x',1,1,job())
  with self.assertRaises(ValueError):a.snapshot([x,{**x,'payload':job(9)}],2,2)
 def test_opening_missing_journal_does_not_create_it(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'absent.sqlite'
   with self.assertRaises(FileNotFoundError):a.read_events(p)
   self.assertFalse(p.exists())
 def test_invalid_payload_is_rejected_before_insertion(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'facts.sqlite'
   with self.assertRaises(ValueError):a.append_events(p,[event('a','job','x',1,1,{'priority':True,'skill':'m','deadline':4})])
   self.assertFalse(p.exists())

class BoundsAndOracleTests(unittest.TestCase):
 def test_job_bound_is_explicit(self):
  with self.assertRaises(ValueError):a.allocate(state(*[event(str(i),'job',str(i),0,0,job()) for i in range(33)]))
 def test_resource_bound_is_explicit(self):
  with self.assertRaises(ValueError):a.allocate(state(*[event(str(i),'resource',str(i),0,0,resource()) for i in range(11)]))
 def test_exact_matching_agrees_with_independent_exhaustive_oracle(self):
  # Independent product enumeration, not the production DP or its ranking helper.
  rng=random.Random(2740)
  for _ in range(200):
   workers={f'r{i}':resource(('m',) if rng.random()<.7 else ('e',),rng.random()<.8,{f'j{k}':rng.randrange(6) for k in range(4)}) for i in range(3)}
   jobs={f'j{i}':job(rng.randrange(1,10),rng.choice(['m','e']),rng.randrange(6)) for i in range(4)}
   possibilities=[]
   for assignment in itertools.product([None,*workers],repeat=4):
    used=[r for r in assignment if r is not None]
    if len(used)!=len(set(used)):continue
    pairs=[];priority=cost=0;valid=True
    for (jid,j),rid in zip(sorted(jobs.items()),assignment):
     if rid is None:continue
     w=workers[rid]
     if not w['available'] or j['skill'] not in w['skills'] or w['costs'][jid]>j['deadline']:
      valid=False;break
     pairs.append((jid,rid));priority+=j['priority'];cost+=w['costs'][jid]
    if valid:possibilities.append((-priority,cost,tuple(pairs)))
   best=min(possibilities)
   s=state(*[event(k,'resource',k,0,0,v) for k,v in workers.items()],*[event(k,'job',k,0,0,v) for k,v in jobs.items()])
   got=a.allocate(s)
   self.assertEqual((-got['covered_priority'],got['travel_cost'],tuple(got['assignments'].items())),best)
 def test_ties_use_stable_identifiers(self):
  s=state(event('a','resource','z',0,0,resource(costs={'j':1})),event('b','resource','a',0,0,resource(costs={'j':1})),event('j','job','j',0,0,job()))
  self.assertEqual(a.allocate(s)['assignments'],{'j':'a'})
 def test_snapshot_outputs_do_not_alias_input_records(self):
  data=events();s=a.snapshot(data,50,50);s['job/pump']['payload']['priority']=999
  self.assertEqual(data[2]['payload']['priority'],6)
 def test_unavailable_resource_cannot_be_assigned(self):
  s=state(event('r','resource','r',0,0,resource(available=False,costs={'j':0})),event('j','job','j',0,0,job()))
  self.assertEqual(a.allocate(s)['assignments'],{})

class CLITests(unittest.TestCase):
 def test_ambiguous_duplicate_json_keys_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'duplicate.json';p.write_text('[{"event_id":"a","kind":"job","entity":"j","valid_at":1,"known_at":1,"payload":{"priority":1,"priority":8,"skill":"m","deadline":5}}]')
   result=subprocess.run([sys.executable,'main.py','replay',str(p),'--valid-at','2','--before','1','--after','2','--out',str(Path(d)/'out')],capture_output=True,text=True)
   self.assertEqual(result.returncode,2)
   self.assertIn('duplicate JSON key',result.stderr)
 def test_report_escapes_source_text_without_executing_it(self):
  from afterfact.report import render
  data=events();data[6]['payload']['label']='<script>alert(1)</script>'
  report=a.explain(data,50,50,100);report['input_provenance']='User input'
  document=render(report)
  self.assertNotIn('<script>',document)
  self.assertIn('&lt;script&gt;',document)
 def test_demo_and_persistent_replay_have_identical_decisions(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   first=subprocess.run([sys.executable,'main.py','demo','--out',str(root/'demo')],capture_output=True,text=True)
   self.assertEqual(first.returncode,0,first.stderr)
   replay=subprocess.run([sys.executable,'main.py','replay',str(root/'demo/events.json'),'--valid-at','50','--before','50','--after','100','--out',str(root/'replay'),'--db',str(root/'facts.sqlite')],capture_output=True,text=True)
   self.assertEqual(replay.returncode,0,replay.stderr)
   a=json.loads((root/'demo/report.json').read_text());b=json.loads((root/'replay/report.json').read_text())
   self.assertEqual(a['after'],b['after']);self.assertEqual(a['witness'],b['witness'])
   self.assertEqual(b['input_provenance'],'User-supplied events; provenance is not inferred.')
 def test_invalid_file_exits_two_without_success_report(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'bad.json';p.write_text('{}')
   result=subprocess.run([sys.executable,'main.py','replay',str(p),'--valid-at','1','--before','1','--after','2','--out',str(Path(d)/'out')],capture_output=True,text=True)
   self.assertEqual(result.returncode,2);self.assertFalse((Path(d)/'out/report.json').exists())

if __name__=='__main__':unittest.main()
