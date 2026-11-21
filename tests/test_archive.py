from dataclasses import replace
from fractions import Fraction
import sqlite3
import unittest

from archive.commit import ArchiveWriteError
from archive.peak import PeakResult
from maintenance.session import maintenance
from record.mode import stop
from record.samples import Sample
from tests.rig import StationRig


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.rig = StationRig(self)

    def test_first_peak(self):
        self.rig.register(threshold=11)
        self.rig.record('R', [-11, 11])
        stop(self.rig.device)
        signed = self.rig.archive('R')
        recalled = self.rig.reports.get_by_receipt(signed.receipt_id)
        self.assertEqual(recalled.report.peak, PeakResult(Fraction(11), 1, False))
        self.assertEqual(recalled.report.original.samples, (Sample(1, -11), Sample(2, 11)))

    def test_fraction_equal(self):
        self.rig.register(scale='1/10', threshold='3/10')
        self.rig.record('R', [-3])
        stop(self.rig.device)
        signed = self.rig.archive('R')
        self.rig.reopen()
        report = self.rig.reports.get_report(signed.report.report_id)
        self.assertIsInstance(report.peak.magnitude, Fraction)
        self.assertEqual(report.peak, PeakResult(Fraction(3, 10), 1, False))
        self.assertEqual(report.original.rule.scale, Fraction(1, 10))
        self.assertEqual(report.original.rule.threshold, Fraction(3, 10))

    def test_source_mismatch(self):
        self.rig.register()
        self.rig.record('R', [-7, 11])
        other = self.rig.record('S', [29])
        stop(self.rig.device)
        self.rig.source.after_read = lambda original: other
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            self.rig.archive('R')
        self.assertEqual(self.rig.counts()[:2], (0, 0))
        self.assertIsNone(self.rig.reports.find_by_recording('bench-4', 'S'))
        self.assertEqual(self.rig.archive('R').report.peak.magnitude, 11)

    def test_invalid_originals(self):
        self.rig.register()
        original = self.rig.record('R', [-7, 11])
        stop(self.rig.device)
        cases = (
            replace(original, device_id='another-bench'),
            replace(original, shift_id=' '),
            replace(original, samples=()),
            replace(original, samples=(Sample(2, 11),)),
            replace(original, samples=(Sample(1, True),)),
            replace(original, rule=replace(original.rule, scale=Fraction(0))),
            replace(original, rule=replace(original.rule, threshold=Fraction(-1))),
        )
        for invalid in cases:
            with self.subTest(original=invalid):
                self.rig.source.after_read = lambda valid: invalid
                with self.assertRaises(ValueError):
                    self.rig.archive('R')
                self.assertEqual(self.rig.counts()[:2], (0, 0))
        with self.assertRaises(KeyError):
            self.rig.archive('unknown')
        self.assertEqual(self.rig.counts()[:2], (0, 0))

    def test_retry_after_commit_failure(self):
        self.rig.register()
        original = self.rig.record('R', [-7, 11])
        stop(self.rig.device)
        self.rig.reject_receipt_writes()
        with self.assertRaises(ArchiveWriteError) as failure:
            self.rig.archive('R')
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        self.assertIn('fixture receipt write failed', str(failure.exception.__cause__))
        self.assertIs(self.rig.originals.get('R'), original)
        self.rig.reopen()
        self.assertEqual(self.rig.counts()[:2], (0, 0))
        self.assertIsNone(self.rig.reports.find_by_recording(self.rig.device.device_id, 'R'))
        first = self.rig.archive('R')
        second = self.rig.archive('R')
        self.assertEqual(first, second)
        self.assertEqual(first.report.peak, PeakResult(Fraction(11), 2, True))
        self.assertEqual(self.rig.reports.get_by_receipt(first.receipt_id), first)
        self.assertEqual(self.rig.counts()[:2], (1, 1))
        self.assertEqual(self.rig.source.reads, ['R', 'R'])

    def test_failure_at_sqlite_commit(self):
        self.rig.register()
        self.rig.record('R', [-7, 11])
        stop(self.rig.device)
        self.rig.reject_next_commit()
        with self.assertRaises(ArchiveWriteError):
            self.rig.archive('R')
        self.assertEqual(self.rig.denied_commits, 1)
        self.assertTrue(self.rig.holds_original('R'))
        self.rig.reopen()
        self.assertEqual(self.rig.counts()[:2], (0, 0))
        result = self.rig.archive('R')
        self.assertEqual(result.report.peak, PeakResult(Fraction(11), 2, True))
        self.assertEqual(self.rig.counts()[:2], (1, 1))

    def test_mode_guard(self):
        self.rig.register()
        self.rig.record('R', [-7, 11])
        with self.assertRaises(RuntimeError):
            self.rig.archive('R')
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        with self.assertRaises(RuntimeError):
            self.rig.archive('R')
        self.assertEqual(self.rig.source.reads, [])
        self.assertEqual(self.rig.counts()[:2], (0, 0))
        maintenance(self.rig.device, False)
        signed = self.rig.archive('R')
        self.assertEqual(signed.report.peak.magnitude, 11)
        maintenance(self.rig.device, True)
        with self.assertRaises(RuntimeError):
            self.rig.archive('R')
        self.assertEqual(self.rig.counts()[:2], (1, 1))

    def test_lossless_large_values(self):
        raw = -((1 << 15000) + 7)
        scale = Fraction(1, 1 << 15001)
        self.rig.register(scale=scale, threshold=Fraction(1, 2))
        self.rig.record('large', [raw, 0])
        stop(self.rig.device)
        signed = self.rig.archive('large')
        self.rig.reopen()
        recalled = self.rig.reports.get_by_receipt(signed.receipt_id)
        self.assertEqual(recalled.report.original.samples, (Sample(1, raw), Sample(2, 0)))
        self.assertEqual(recalled.report.original.rule.scale, scale)
        self.assertEqual(recalled.report.peak, PeakResult(Fraction(-raw, 1 << 15001), 1, True))
