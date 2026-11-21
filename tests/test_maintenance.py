import unittest

from maintenance.discard import discard
from maintenance.history import DiscardFact
from maintenance.session import maintenance
from record.mode import DeviceMode, stop
from record.runs import open as open_recording
from record.source import DiscardedOriginal
from tests.rig import StationRig


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.rig = StationRig(self)
        self.rig.register()

    def discard(self, recording_id, reason='夹具松脱'):
        return discard(self.rig.device, self.rig.originals, self.rig.history, recording_id, reason)

    def test_discard_unarchived(self):
        original = self.rig.record('C', [3])
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        self.assertEqual(self.discard('C'), DiscardFact('bench-4', 'C', '夹具松脱'))
        maintenance(self.rig.device, False)
        with self.assertRaises(DiscardedOriginal):
            self.rig.archive('C')
        self.assertEqual(self.rig.history.find('bench-4', 'C').reason, '夹具松脱')
        self.assertIs(self.rig.originals.get('C'), original)
        self.assertEqual(self.rig.counts()[:3], (0, 0, 1))

    def test_mode_cycle(self):
        self.rig.record('C', [3])
        with self.assertRaises(RuntimeError):
            maintenance(self.rig.device, True)
        with self.assertRaises(RuntimeError):
            self.discard('C')
        stop(self.rig.device)
        with self.assertRaises(RuntimeError):
            maintenance(self.rig.device, False)
        with self.assertRaises(RuntimeError):
            self.discard('C')
        self.assertEqual(maintenance(self.rig.device, True), DeviceMode.MAINTENANCE)
        with self.assertRaises(RuntimeError):
            open_recording(self.rig.book, self.rig.registry, 'D', 'early', 'K', 'J1')
        with self.assertRaises(KeyError):
            self.discard('unknown')
        with self.assertRaises(ValueError):
            self.discard('C', ' ')
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        self.assertEqual(maintenance(self.rig.device, False), DeviceMode.STOPPED)
        self.assertEqual(self.rig.archive('C').report.peak.magnitude, 3)

    def test_reason_replay(self):
        self.rig.record('C', [3])
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        first = self.discard('C')
        self.assertEqual(self.discard('C'), first)
        with self.assertRaisesRegex(ValueError, 'conflicting discard reason'):
            self.discard('C', '电缆折损')
        self.assertEqual(self.rig.history.find('bench-4', 'C'), first)
        self.assertEqual(self.rig.counts()[:3], (0, 0, 1))

    def test_reopen_discard(self):
        self.rig.record('C', [3])
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        first = self.discard('C')
        maintenance(self.rig.device, False)
        self.rig.reopen()
        self.assertTrue(self.rig.holds_original('C'))
        self.assertEqual(self.rig.history.find('bench-4', 'C'), first)
        with self.assertRaises(DiscardedOriginal):
            self.rig.source.read_original('C')
        with self.assertRaises(DiscardedOriginal):
            self.rig.archive('C')
        self.assertEqual(self.rig.counts()[:3], (0, 0, 1))

    def test_keep_signed_recording(self):
        recording_id = 'physical-run-R'
        self.rig.record(recording_id, [-7, 11])
        stop(self.rig.device)
        signed = self.rig.archive(recording_id)
        self.assertNotEqual(signed.report.report_id, recording_id)
        self.assertNotEqual(signed.receipt_id, recording_id)
        maintenance(self.rig.device, True)
        with self.assertRaisesRegex(ValueError, 'signed report'):
            self.discard(recording_id)
        self.assertIsNone(self.rig.history.find('bench-4', recording_id))
        self.assertEqual(self.rig.reports.get_by_receipt(signed.receipt_id), signed)
        self.assertEqual(self.rig.counts()[:3], (1, 1, 0))
