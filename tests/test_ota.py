import unittest
import numpy as np
from ota_flow import instance,ac_metrics,meets


class OTATests(unittest.TestCase):
    def test_pin_order_and_duplicate_rejection(self):
        declaration='.subckt OPAMP_TWO_STAGE VOUT VN VP CS_BIAS DIFFPAIR_BIAS GND VDD'
        self.assertEqual(instance(declaration),'XOTA VOUT VP VN IB2 IB1 0 VDD OPAMP_TWO_STAGE')
        self.assertEqual(instance(declaration,True),'XOTA VOUT VP VOUT IB2 IB1 0 VDD OPAMP_TWO_STAGE')
        with self.assertRaises(ValueError):instance(declaration.replace('VP','VN'))

    def test_known_single_pole_response(self):
        frequency=np.geomspace(1,1e8,1000);response=100/(1+1j*frequency/1e4)
        metrics=ac_metrics(np.column_stack([frequency,response.real,response.imag]))
        self.assertAlmostEqual(metrics['low_frequency_gain_db'],40,places=5)
        self.assertAlmostEqual(metrics['unity_gain_hz']/1e6,1,places=3)
        self.assertAlmostEqual(metrics['phase_margin_deg'],90.573,places=2)

    def test_missing_crossing_and_wrong_polarity_unqualified(self):
        frequency=np.geomspace(1,1e3,10)
        response=-100/(1+1j*frequency/1e4)
        metrics=ac_metrics(np.column_stack([frequency,response.real,response.imag]))
        self.assertFalse(metrics['positive_low_frequency_polarity'])
        self.assertIsNone(metrics['phase_margin_deg'])
        self.assertIsNone(metrics['unity_gain_hz'])
