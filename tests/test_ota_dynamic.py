import unittest
import numpy as np
from ota_dynamic import step_metrics


class StepMetricsTests(unittest.TestCase):
    def test_settling_and_persistent_error(self):
        t=np.linspace(0,14e-6,1401)
        vin=np.where((t>=2e-6)&(t<8e-6),1.,.9)
        response=.9+.1*(1-np.exp(-np.maximum(t-2e-6,0)/.2e-6))
        after=t>=8e-6
        response[after]=.9+.1*np.exp(-(t[after]-8e-6)/.2e-6)
        result=step_metrics(np.column_stack((t,vin,response)))
        for step in result['steps']:
            self.assertIsNotNone(step['settling_to_1mv_seconds'])
            self.assertLess(step['settling_to_1mv_seconds'],1e-6)
        response+=.01
        result=step_metrics(np.column_stack((t,vin,response)))
        self.assertTrue(all(s['settling_to_1mv_seconds'] is None for s in result['steps']))
        self.assertTrue(all(s['settling_to_final_level_1mv_seconds'] is not None for s in result['steps']))

    def test_invalid_time_rejected(self):
        with self.assertRaises(ValueError):step_metrics(np.ones((100,3)))
