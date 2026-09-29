import unittest

from physical_flow import mirror_instance


class PhysicalTests(unittest.TestCase):
    def test_schematic_pin_order(self):
        self.assertEqual(mirror_instance(".subckt CMIRROR VREF VOUT VSS B\n.ends"),
                         "XMIRROR VREF VOUT 0 0 CMIRROR")

    def test_extracted_pin_order(self):
        self.assertEqual(mirror_instance(".subckt CMIRROR B VOUT VREF VSS\n.ends"),
                         "XMIRROR 0 VOUT VREF 0 CMIRROR")

    def test_unrecognized_pins_rejected(self):
        with self.assertRaises(ValueError):
            mirror_instance(".subckt CMIRROR B VOUT VREF WRONG\n.ends")
