import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from ota_flow import ac_metrics
from ota_handoff import audit


class HandoffTests(unittest.TestCase):
    def fixture(self,root):
        spec=dict(corners=['tt'],temperatures_c=[27],tracking_input_range_v=[.8,1.1],
            minimum_gain_db=40,minimum_unity_gain_hz=5e5,minimum_phase_margin_deg=60,
            maximum_power_mw=1,maximum_tracking_error_mv=20)
        (root/'specification.json').write_text(json.dumps(spec))
        (root/'layout.gds').write_bytes(b'fixture')
        (root/'magic.log').write_text('DRC_COUNT=0\n')
        (root/'lvs.log').write_text('Circuits match uniquely.\n')
        f=np.geomspace(1,1e8,601);h=110/(1+1j*f/1e4);data=np.column_stack((f,h.real,h.imag))
        rows=[]
        for source in ('schematic','extracted_capacitance'):
            folder=root/f'{source}-tt-27';folder.mkdir()
            np.savetxt(folder/'ac.dat',data,header='frequency real imaginary',comments='')
            np.savetxt(folder/'op.dat',[[0,.9,.9,-.1e-3/1.8,.1e-3]],header='scale out in supply power',comments='')
            v=np.linspace(.8,1.1,13)
            np.savetxt(folder/'tracking.dat',np.column_stack((v,v,v)),header='scale in out',comments='')
            rows.append(dict(source=source,corner='tt',temperature_c=27,power_mw=.1,
                worst_tracking_error_mv=0,**ac_metrics(data)))
        summary=dict(specification_pass=True,layout_sha256=hashlib.sha256(b'fixture').hexdigest(),electrical=rows)
        (root/'summary.json').write_text(json.dumps(summary));return summary

    def test_valid_and_duplicate_condition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);summary=self.fixture(root);audit(root)
            summary['electrical'][1]=summary['electrical'][0]
            (root/'summary.json').write_text(json.dumps(summary))
            with self.assertRaises(ValueError):audit(root)

    def test_property_errors_and_changed_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            (root/'lvs.log').write_text('Circuits match uniquely.\nProperty errors were found\n')
            with self.assertRaises(ValueError):audit(root)
            (root/'lvs.log').write_text('Circuits match uniquely.\n')
            path=root/'schematic-tt-27/ac.dat';data=np.loadtxt(path,skiprows=1);data[:,1:]*=.01
            np.savetxt(path,data,header='frequency real imaginary',comments='')
            with self.assertRaises(ValueError):audit(root)
