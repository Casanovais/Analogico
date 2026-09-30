import unittest
import torch
from rl_search import score, distribution, policy_model, episode, baseline


class RLTests(unittest.TestCase):
    def rows(self):
        return [dict(config=[1+i%3, .5+.5*(i//3),2],reference_ua=10,
            geometry={'area_um2':100+i}, verification={'drc_pass':True,'lvs_pass':True},
            worst_error_percent=4, worst_reference_voltage_v=.8, minimum_bandwidth_hz=1e8) for i in range(12)]

    def test_invalid_layout_and_missing_measurement_rejected(self):
        r=self.rows()[0];goal=[5,.9,1e7]
        self.assertTrue(score(r,goal)[1])
        r['worst_error_percent']=0
        self.assertTrue(score(r,goal)[1])
        r['verification']['lvs_pass']=False
        self.assertFalse(score(r,goal)[1])
        r['verification']['lvs_pass']=True;r['minimum_bandwidth_hz']=None
        self.assertFalse(score(r,goal)[1])

    def test_action_mask_and_query_budget(self):
        torch.manual_seed(0);policy=policy_model();rows=self.rows()
        dist=distribution(policy,rows,[0,1,2,3],[5,.9,1e7],8)
        self.assertTrue(torch.all(dist.probs[:4]==0))
        selected,_,_,_=episode(policy,rows,[5,.9,1e7],0)
        self.assertEqual(len(selected),8)
        self.assertEqual(len(set(selected)),8)
        for strategy in ('random','bayesian'):
            self.assertEqual(selected[:4],baseline(rows,[5,.9,1e7],0,strategy)[:4])
