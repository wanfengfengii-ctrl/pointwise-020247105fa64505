from fractions import Fraction
import unittest

from archive.peak import PeakResult
from archive.storage import initialize_station
from handover.issue import issue
from handover.lookup import lookup
from maintenance.discard import discard
from maintenance.session import maintenance
from record.mode import stop
from record.samples import Sample
from record.source import DiscardedOriginal
from rules.freeze import FrozenRule
from tests.rig import StationRig


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.rig = StationRig(self)

    def issue(self, shift_id, *references):
        return issue(self.rig.reports, self.rig.notes, shift_id, references)

    def recall(self, reference):
        return lookup(self.rig.reports, self.rig.notes, reference)

    def test_offline_shift_review(self):
        self.rig.register()
        self.rig.register(scale=2, revision_id='J2')
        self.rig.record('A', [-7, 11])
        self.rig.record('B', [-5, 5], revision_id='J2')
        stop(self.rig.device)
        first = self.rig.archive('A')
        second = self.rig.archive('B')
        references = (first.report.report_id, second.report.report_id)
        issued = self.issue('early', *reversed(references))
        self.rig.device.power_off()
        self.rig.reopen()
        with self.assertRaises(RuntimeError):
            self.rig.source.read_original('A')
        note = self.recall(issued.handover_id)
        self.assertEqual(note, issued)
        self.assertEqual((note.shift_id, note.report_ids, note.exceeded_count), ('early', references, 1))
        expected = (
            ('A', (Sample(1, -7), Sample(2, 11)), 'J1', 1, PeakResult(Fraction(11), 2, True)),
            ('B', (Sample(1, -5), Sample(2, 5)), 'J2', 2, PeakResult(Fraction(10), 1, False)),
        )
        for reference, signed, (run, samples, revision, scale, peak) in zip(
            references, (first, second), expected, strict=True,
        ):
            recalled = self.recall(signed.receipt_id)
            original = recalled.report.original
            self.assertEqual(recalled.report, self.rig.reports.get_report(reference))
            self.assertEqual((original.device_id, original.recording_id, original.shift_id),
                             ('bench-4', run, 'early'))
            self.assertEqual(original.rule, FrozenRule('K', revision, Fraction(scale), Fraction(10)))
            self.assertEqual(original.samples, samples)
            self.assertEqual(recalled.report.peak, peak)

    def test_init_reopen(self):
        self.rig.register(scale='3/2', threshold='7/2', revision_id='personal')
        self.rig.record('pulse-81', [2, -4], shift_id='swing', revision_id='personal')
        self.rig.record('pulse-82', [1], shift_id='swing', revision_id='personal')
        stop(self.rig.device)
        signed = self.rig.archive('pulse-81')
        note = self.issue('swing', signed.report.report_id)
        maintenance(self.rig.device, True)
        fact = discard(self.rig.device, self.rig.originals, self.rig.history, 'pulse-82', '定位销歪斜')
        maintenance(self.rig.device, False)
        self.assertEqual(self.rig.counts(), (1, 1, 1, 1, 1))
        initialize_station(self.rig.connection)
        initialize_station(self.rig.connection)
        self.rig.reopen()
        self.assertEqual(self.rig.counts(), (1, 1, 1, 1, 1))
        self.assertEqual(self.recall(signed.receipt_id), signed)
        self.assertEqual(self.recall(note.handover_id), note)
        self.assertEqual(note.exceeded_count, 1)
        self.assertEqual(signed.report.original.samples, (Sample(1, 2), Sample(2, -4)))
        self.assertEqual(signed.report.peak, PeakResult(Fraction(6), 2, True))
        self.assertTrue(self.rig.holds_original('pulse-82'))
        self.assertEqual(self.rig.history.find('bench-4', 'pulse-82'), fact)
        with self.assertRaises(DiscardedOriginal):
            self.rig.archive('pulse-82')
        self.assertEqual(self.rig.counts(), (1, 1, 1, 1, 1))

    def test_unknown_lookup(self):
        self.rig.register()
        self.rig.record('A', [-7, 11])
        stop(self.rig.device)
        signed = self.rig.archive('A')
        note = self.issue('early', signed.report.report_id)
        for unknown in ('receipt-0000000000000000999', 'handover-0000000000000000999',
                        'receipt-9999999999999999999', signed.report.report_id):
            with self.subTest(reference=unknown):
                with self.assertRaises(KeyError):
                    self.recall(unknown)
        self.assertEqual(self.recall(signed.receipt_id), signed)
        self.assertEqual(self.recall(note.handover_id), note)

    def test_reject_mixed_shift(self):
        self.rig.register()
        self.rig.record('A', [6], shift_id='early')
        self.rig.record('B', [13], shift_id='late')
        stop(self.rig.device)
        first = self.rig.archive('A')
        second = self.rig.archive('B')
        with self.assertRaisesRegex(ValueError, 'another shift'):
            self.issue('early', first.report.report_id, second.report.report_id)
        self.assertEqual(self.rig.counts(), (2, 2, 0, 0, 0))
        self.assertEqual(self.recall(first.receipt_id), first)
        self.assertEqual(self.recall(second.receipt_id), second)

    def test_duplicate(self):
        self.rig.register()
        self.rig.record('R', [20])
        stop(self.rig.device)
        signed = self.rig.archive('R')
        with self.assertRaisesRegex(ValueError, 'duplicate recording'):
            self.issue('early', signed.report.report_id, signed.report.report_id)
        self.assertEqual(self.rig.counts(), (1, 1, 0, 0, 0))
        self.assertEqual(self.recall(signed.receipt_id), signed)

    def test_unknown_report(self):
        self.rig.register()
        self.rig.record('R', [20])
        stop(self.rig.device)
        signed = self.rig.archive('R')
        with self.assertRaises(KeyError):
            self.issue('early', signed.report.report_id, 'report-0000000000000000999')
        self.assertEqual(self.rig.counts(), (1, 1, 0, 0, 0))
        self.assertEqual(self.recall(signed.receipt_id), signed)

    def test_empty_handover(self):
        issued = self.issue('early')
        self.rig.reopen()
        self.assertEqual(self.recall(issued.handover_id), issued)
        self.assertEqual((issued.report_ids, issued.exceeded_count), ((), 0))
        self.assertEqual(self.rig.counts(), (0, 0, 0, 1, 0))
