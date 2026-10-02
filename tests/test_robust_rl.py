import unittest
import numpy as np
import torch
from robust_rl import ActorCritic, features, trace, record, fit_transfer


class RobustRLTests(unittest.TestCase):
    def rows(self,current=30):
        return [dict(config=[1+i%3,.5+.5*(i//3),2],reference_ua=current,
            geometry={'area_um2':100+i},verification={'drc_pass':True,'lvs_pass':True},
            worst_error_percent=4+i, worst_reference_voltage_v=.8, minimum_bandwidth_hz=1e8,
            seconds=2.,generation_seconds=3.) for i in range(12)]

    def test_unqueried_labels_do_not_change_policy_features(self):
        rows=self.rows();before=features(rows,[0,1],[5,.9,1e7],6)
        rows[2]['worst_error_percent']=10000
        rows[2]['worst_reference_voltage_v']=10000
        rows[2]['minimum_bandwidth_hz']=1
        torch.testing.assert_close(before,features(rows,[0,1],[5,.9,1e7],6))

    def test_masked_actions_and_shared_initialization(self):
        rows=self.rows();model=ActorCritic();goal=[5,.9,1e7]
        traces=[trace(rows,goal,0,6,m,model,.5) for m in ('ppo','hybrid','bayesian','random')]
        for selected in traces:
            self.assertEqual(len(selected),6)
            self.assertEqual(len(set(selected)),6)
            self.assertEqual(selected[:2],traces[0][:2])
        mask=torch.zeros(12,dtype=torch.bool);mask[:2]=True
        dist,_=model(features(rows,[0,1],goal,6),mask)
        self.assertTrue(torch.all(dist.probs[:2]==0))

    def test_cost_counts_failed_tasks_and_reuses_layouts(self):
        rows=self.rows()
        failed=record(rows,[1,.9,1e7],[0,1,2])
        self.assertFalse(failed['success'])
        self.assertEqual(failed['queries_to_stop'],3)
        self.assertEqual(failed['estimated_oracle_seconds'],6)
        passed=record(rows,[5,.9,1e7],[0,1,2])
        self.assertEqual(passed['queries_to_stop'],1)
        self.assertEqual(passed['estimated_oracle_seconds'],2)
        self.assertEqual(passed['estimated_cold_oracle_seconds'],5)

    def test_transfer_fit_and_finite_choice(self):
        training=self.rows(10)+self.rows(20);validation=self.rows(15)
        weights,meta=fit_transfer(training,validation)
        self.assertTrue(np.all(np.isfinite(weights)))
        selected=trace(self.rows(),[5,.9,1e7],0,6,'transfer',transfer=weights)
        self.assertEqual(len(set(selected)),6)

    def test_attention_history_has_no_hidden_measurements(self):
        from robust_rl import AttentionActorCritic
        rows=self.rows();selected=[0,1];goal=[5,.9,1e7]
        state=features(rows,selected,goal,6,True)
        rows[2]['worst_error_percent']=10000
        rows[2]['minimum_bandwidth_hz']=1
        torch.testing.assert_close(state,features(rows,selected,goal,6,True))
        model=AttentionActorCritic();mask=torch.zeros(12,dtype=torch.bool);mask[selected]=True
        dist,value=model(state,mask)
        self.assertTrue(torch.all(dist.probs[selected]==0))
        self.assertTrue(torch.isfinite(value))
        batch_dist,batch_value=model(torch.stack([state,state]),torch.stack([mask,mask]))
        self.assertEqual(batch_value.shape,(2,))
        torch.testing.assert_close(batch_dist.probs[0],dist.probs)
