import unittest
from workstation.runner import evidence_pass


class WorkstationTests(unittest.TestCase):
    def test_incomplete_checks_rejected(self):
        for kind in ('drc','lvs','pex','simulation'):
            self.assertFalse(evidence_pass(kind,{}))
        self.assertFalse(evidence_pass('drc',{'complete':True,'error_count':False}))
        self.assertFalse(evidence_pass('lvs',{'complete':True,'match':True,'property_errors':0}))

    def test_simulation_requires_unique_complete_coverage(self):
        good=dict(complete=True,required_conditions=['tt-27','ff-85'],
                  observed_conditions=['ff-85','tt-27'],meets_specification=True)
        self.assertTrue(evidence_pass('simulation',good))
        good['observed_conditions']=['tt-27','tt-27']
        self.assertFalse(evidence_pass('simulation',good))

    def test_explicit_successful_evidence(self):
        self.assertTrue(evidence_pass('drc',{'complete':True,'error_count':0}))
        self.assertTrue(evidence_pass('lvs',dict(complete=True,match=True,device_parameters_checked=True,property_errors=0)))
        self.assertTrue(evidence_pass('pex',dict(complete=True,topology_checked=True,
                                              resistance_extracted=True,capacitance_extracted=True)))
