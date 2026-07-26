import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ble_nus import BleNusServer


class BleNusUuidTests(unittest.TestCase):
    def test_smartbag_uses_dedicated_ble_uuids(self):
        self.assertEqual(BleNusServer.NUS_SERVICE_UUID, "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
        self.assertEqual(BleNusServer.NUS_RX_UUID, "6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
        self.assertEqual(BleNusServer.NUS_TX_UUID, "6E400003-B5A3-F393-E0A9-E50E24DCCA9E")


if __name__ == "__main__":
    unittest.main()
