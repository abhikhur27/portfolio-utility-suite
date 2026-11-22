import unittest
from stallwitness import Sample, analyze, compare, read_vcd, render_html

def wave(rows, extra=""):
    header='$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 v link_valid $end\n$var wire 1 r link_ready $end\n$var wire 8 d link_data [7:0] $end\n'+extra+'$upscope $end\n$enddefinitions $end\n'
    body=[]
    for i,(v,r,d) in enumerate(rows):
        body.extend([f'#{10*i}', '0!',f'{v}v',f'{r}r',f'b{d:08b} d',f'#{10*i+5}','1!'])
    return header+'\n'.join(body)

class Tests(unittest.TestCase):
    def test_preedge_sampling_and_accepted_beats(self):
        rows=read_vcd(wave([(1,0,7),(1,1,7),(1,1,9)]),'tb.clk','tb.link')
        result=analyze(rows)
        self.assertEqual(result['accepted'],[7,9]);self.assertEqual(result['violations'],[])

    def test_post_edge_changes_do_not_change_sample(self):
        text=wave([(1,1,7),(1,1,9)]).replace('#5\n1!','#5\n1!\nb00000100 d')
        self.assertEqual(read_vcd(text,'tb.clk','tb.link')[0].data,7)

    def test_data_must_hold_through_accepting_edge(self):
        result=analyze([Sample(0,5,1,0,7),Sample(1,15,1,1,8)])
        self.assertEqual(result['violations'][0]['kind'],'data_changed_while_stalled')
        self.assertEqual(result['violations'][0]['previous_data'],7)

    def test_valid_cannot_be_withdrawn_under_stall(self):
        result=analyze([Sample(0,5,1,0,7),Sample(1,15,0,0,None)])
        self.assertEqual(result['violations'][0]['kind'],'valid_withdrawn')

    def test_reset_discards_an_old_hold(self):
        result=analyze([Sample(0,5,1,0,7),Sample(1,15,0,0,0,True),Sample(2,25,1,1,9)])
        self.assertEqual(result['violations'],[])

    def test_differential_mismatch(self):
        a=analyze([Sample(0,5,1,1,1),Sample(1,15,1,1,4)])
        b=analyze([Sample(0,5,1,1,1),Sample(1,15,1,1,2)])
        d=compare(a,b)
        self.assertEqual(d['index'],1);self.assertEqual(d['expected'],2);self.assertEqual(d['actual'],4)

    def test_differential_missing_transfer(self):
        a=analyze([Sample(0,5,1,1,1)])
        b=analyze([Sample(0,5,1,1,1),Sample(1,15,1,1,2)])
        self.assertEqual(compare(a,b)['kind'],'missing_transfer')

    def test_differential_can_ignore_latency(self):
        a=analyze([Sample(0,5,1,0,1),Sample(1,15,1,1,1)])
        b=analyze([Sample(0,5,1,1,1)])
        self.assertIsNone(compare(a,b))

    def test_unknown_valid_is_not_silently_zero(self):
        text=wave([(1,1,7)]).replace('1v','xv')
        with self.assertRaisesRegex(ValueError,'unknown valid'):read_vcd(text,'tb.clk','tb.link')

    def test_inactive_unknown_data_is_legal(self):
        text=wave([(0,1,7)]).replace('b00000111 d','bxxxxxxxx d')
        self.assertEqual(analyze(read_vcd(text,'tb.clk','tb.link'))['violations'],[])

    def test_unknown_active_data_is_a_failure(self):
        text=wave([(1,1,7)]).replace('b00000111 d','bxxxxxxxx d')
        self.assertEqual(analyze(read_vcd(text,'tb.clk','tb.link'))['violations'][0]['kind'],'unknown_active_data')

    def test_missing_signal_is_actionable(self):
        with self.assertRaisesRegex(ValueError,'tb.absent_valid'):read_vcd(wave([(0,0,0)]),'tb.clk','tb.absent')

    def test_bad_header_rejected(self):
        with self.assertRaisesRegex(ValueError,'enddefinitions'):read_vcd('#0\n0!','tb.clk','tb.link')

    def test_html_escapes_untrusted_title(self):
        self.assertNotIn('<script>',render_html(analyze([]),'<script>'))

if __name__=='__main__':unittest.main()
