import itertools,json,random,unittest
from rulesplit import Box,subtract,load_policy,classify,compile_plan,verify_plan,split_classify,prefixes
from rulesplit.pcap import encode_pcap,read_pcap

POLICY={'default':'drop','rules':[
 {'id':'trusted','action':'allow','src':'10.0.0.0/8','dport':443},
 {'id':'api','action':'drop','dport':443},
 {'id':'dns','action':'allow','proto':'udp','dport':53}]}

class Tests(unittest.TestCase):
 def test_subtraction_exact_disjoint_small_domain(self):
  rng=random.Random(3)
  for _ in range(80):
   a=Box(tuple((0,3) for _ in range(5)))
   b=Box(tuple(sorted((rng.randrange(4),rng.randrange(4))) for _ in range(5)))
   pieces=subtract(a,b)
   for point in itertools.product(range(4),repeat=5):
    self.assertEqual(sum(p.contains(point) for p in pieces),int(a.contains(point) and not b.contains(point)))

 def test_prefix_cover_aligned_exact(self):
  rng=random.Random(11)
  for _ in range(200):
   a,b=sorted([rng.randrange(256),rng.randrange(256)]);parts=prefixes(a,b,8)
   self.assertEqual(sum(h-l+1 for l,h in parts),b-a+1)
   for l,h in parts:self.assertEqual((h-l+1)&(h-l),0);self.assertEqual(l%(h-l+1),0)
   self.assertEqual([x for l,h in parts for x in range(l,h+1)],list(range(a,b+1)))

 def test_naive_offload_has_real_counterexample(self):
  policy=load_policy(POLICY)
  bad={'rows':[{'box':policy['rules'][1]['box'].to_list(),'action':'drop','rule_id':'api'}]}
  witness=verify_plan(policy,bad)
  self.assertFalse(witness['ok']);self.assertEqual(classify(policy,tuple(witness['packet']))[0],'allow')
  self.assertEqual(read_pcap(encode_pcap([tuple(witness['packet'])])),[tuple(witness['packet'])])

 def test_compiled_plan_matches_boundary_and_random_packets(self):
  policy=load_policy(POLICY);rng=random.Random(42)
  packets=[(rng.getrandbits(32),rng.getrandbits(32),rng.randrange(65536),rng.choice([53,443,22,80]),rng.choice([6,17])) for _ in range(3000)]
  packets.extend([(10<<24,0,123,443,6),((11<<24)-1,0,0,443,6),(11<<24,0,0,443,6)])
  plan=compile_plan(policy,packets,16)
  self.assertTrue(verify_plan(policy,plan)['ok'])
  self.assertLessEqual(len(plan['rows']),16)
  self.assertTrue(all(split_classify(policy,plan,p)[0]==classify(policy,p)[0] for p in packets))

 def test_zero_budget_keeps_everything_on_cpu(self):
  policy=load_policy(POLICY);p=(0,0,12,443,6);plan=compile_plan(policy,[p],0)
  self.assertEqual(plan['rows'],[]);self.assertEqual(split_classify(policy,plan,p),('drop','cpu'))

 def test_shadowed_rule_has_no_rows(self):
  policy=load_policy({'default':'drop','rules':[{'id':'a','action':'allow'},{'id':'b','action':'drop','dport':443}]})
  plan=compile_plan(policy,[(0,0,0,443,6)]*5,3)
  self.assertEqual({r['rule_id'] for r in plan['rows']},{'a'})

 def test_invalid_action_rejected(self):
  with self.assertRaises(ValueError):load_policy({'default':'allow','rules':[{'id':'bad','action':'maybe'}]})

 def test_duplicate_rule_id_rejected(self):
  with self.assertRaises(ValueError):load_policy({'default':'drop','rules':[{'id':'a','action':'allow'},{'id':'a','action':'drop'}]})

 def test_ipv6_is_explicitly_unsupported(self):
  with self.assertRaises(ValueError):load_policy({'default':'drop','rules':[{'id':'a','src':'::/0','action':'allow'}]})

 def test_tampered_action_is_detected(self):
  policy=load_policy(POLICY);p=(10<<24,0,123,443,6);plan=compile_plan(policy,[p]*10,8)
  plan['rows'][0]['action']='drop'
  self.assertFalse(verify_plan(policy,plan)['ok'])

 def test_packet_capture_roundtrip(self):
  packets=[(0x0a000001,0xc0000201,1500,443,6),(0xcb007101,0xc0000201,1,53,17)]
  self.assertEqual(read_pcap(encode_pcap(packets)),packets)

 def test_truncated_capture_fails(self):
  with self.assertRaises(ValueError):read_pcap(encode_pcap([(0,0,0,53,17)])[:-1])

 def test_bad_linktype_fails(self):
  blob=bytearray(encode_pcap([]));blob[20:24]=(101).to_bytes(4,'little')
  with self.assertRaisesRegex(ValueError,'Ethernet'):read_pcap(bytes(blob))

if __name__=='__main__':unittest.main()
