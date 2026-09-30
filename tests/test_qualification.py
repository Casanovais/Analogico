import copy
import itertools
import json
import unittest
from pathlib import Path
from qualification import qualify


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(Path('examples/mirror_spec.json').read_text())
        self.summary = {'verification': {'drc_pass': True, 'drc_error_count': 0, 'lvs_pass': True},
            'electrical': [dict(source=s, corner=c, temperature_c=t, reference_ua=20,
                worst_error_percent_0p6_to_1p6v=4, max_reference_voltage_v=0.85,
                bandwidth_3db_hz=1e8) for s,c,t in itertools.product(
                    ('schematic', 'extracted_capacitance'), self.spec['corners'], self.spec['temperatures_c'])]}

    def test_complete_evidence_qualifies_for_review_only(self):
        result = qualify(self.summary, self.spec)
        self.assertTrue(result['review_qualified'])
        self.assertFalse(result['production_qualified'])

    def test_missing_duplicate_and_wrong_current_rejected(self):
        for change in ('missing', 'duplicate', 'current'):
            data = copy.deepcopy(self.summary)
            if change == 'missing':
                data['electrical'].pop()
            elif change == 'duplicate':
                data['electrical'].append(data['electrical'][0])
            else:
                data['electrical'][0]['reference_ua'] = 10
            self.assertFalse(qualify(data, self.spec)['review_qualified'])

    def test_bad_measurements_rejected(self):
        for value in (None, float('nan'), float('inf'), -1, True, 1e6):
            data = copy.deepcopy(self.summary)
            data['electrical'][0]['bandwidth_3db_hz'] = value
            self.assertFalse(qualify(data, self.spec)['review_qualified'])

    def test_physical_and_electrical_failures_rejected(self):
        self.summary['verification']['lvs_pass'] = False
        self.assertFalse(qualify(self.summary, self.spec)['review_qualified'])
        self.summary['verification']['lvs_pass'] = True
        self.summary['electrical'][0]['worst_error_percent_0p6_to_1p6v'] = 6
        self.assertFalse(qualify(self.summary, self.spec)['review_qualified'])
