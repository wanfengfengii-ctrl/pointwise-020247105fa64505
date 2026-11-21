from dataclasses import FrozenInstanceError
from fractions import Fraction
import unittest

from record.mode import DeviceMode, DeviceState, stop
from record.runs import RunBook, append, open as open_recording
from record.samples import Sample
from record.seal import SealedStore, seal
from rules.register import register
from rules.revisions import RevisionRegistry


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.device = DeviceState('bench-2')
        self.book = RunBook(self.device)
        self.originals = SealedStore()
        self.registry = RevisionRegistry()
        self.revision = register(self.registry, 'K', 'J1', 1, 10)

    def open_run(self, recording_id='R', revision_id='J1'):
        return open_recording(self.book, self.registry, recording_id, 'early', 'K', revision_id)

    def test_freeze_revision(self):
        self.open_run()
        register(self.registry, 'K', 'J2', 2, 10)
        append(self.book, 'R', 1, 11)
        original = seal(self.book, self.originals, 'R')
        self.assertEqual((original.rule.rule_id, original.rule.revision_id), ('K', 'J1'))
        self.assertEqual((original.rule.scale, original.rule.threshold), (Fraction(1), Fraction(10)))
        self.assertEqual(self.open_run('S', 'J2').rule.scale, Fraction(2))

    def test_registration(self):
        self.assertIs(register(self.registry, 'K', 'J1', '2/2', Fraction(20, 2)), self.revision)
        with self.assertRaises(ValueError):
            register(self.registry, 'K', 'J1', 2, 10)
        for coefficient, limit in ((0, 10), (-1, 10), (1, -1), (True, 10), (1, False),
                                   (0.1, 10), ('1/0', 10), ('bad', 10)):
            with self.subTest(coefficient=coefficient, limit=limit):
                with self.assertRaises(ValueError):
                    register(self.registry, 'K', 'bad', coefficient, limit)
        with self.assertRaises(ValueError):
            register(self.registry, ' ', 'J1', 1, 10)
        with self.assertRaises(KeyError):
            self.registry.get('K', 'bad')
        self.assertIs(self.registry.get('K', 'J1'), self.revision)

    def test_open_reject(self):
        active = self.open_run()
        with self.assertRaises(KeyError):
            self.open_run('S', 'missing')
        with self.assertRaises(RuntimeError):
            self.open_run('S')
        with self.assertRaises(ValueError):
            self.open_run('R')
        self.assertIs(self.book.get_active('R'), active)
        append(self.book, 'R', 1, 12)
        seal(self.book, self.originals, 'R')
        self.assertEqual(self.open_run('S').recording_id, 'S')

    def test_sealed_waveform(self):
        self.open_run()
        append(self.book, 'R', 1, -7)
        append(self.book, 'R', 2, 11)
        original = seal(self.book, self.originals, 'R')
        self.assertEqual(original.samples, (Sample(1, -7), Sample(2, 11)))
        self.assertEqual((original.device_id, original.recording_id, original.shift_id),
                         ('bench-2', 'R', 'early'))
        with self.assertRaises(ValueError):
            append(self.book, 'R', 3, 9)
        with self.assertRaises(FrozenInstanceError):
            original.samples[0].raw = 9
        self.assertIs(self.originals.get('R'), original)

    def test_next_run(self):
        self.open_run()
        append(self.book, 'R', 1, -7)
        original = seal(self.book, self.originals, 'R')
        self.open_run('S')
        append(self.book, 'S', 1, 23)
        with self.assertRaises(ValueError):
            append(self.book, 'R', 2, 55)
        self.assertIs(self.originals.get('R'), original)
        self.assertEqual(original.samples, (Sample(1, -7),))
        self.assertEqual(original.device_id, 'bench-2')
        self.assertEqual(self.book.get_active('S').samples.snapshot(), (Sample(1, 23),))

    def test_reject_gap(self):
        self.open_run()
        with self.assertRaises(ValueError):
            append(self.book, 'R', 2, 11)
        self.assertEqual(append(self.book, 'R', 1, -7), Sample(1, -7))

    def test_later_gap(self):
        self.open_run()
        append(self.book, 'R', 1, 4)
        for sequence, raw in ((3, 7), (1, 8), (2, True), (2, 1.5), (2, '5'), (2.0, 5)):
            with self.subTest(sequence=sequence, raw=raw):
                with self.assertRaises(ValueError):
                    append(self.book, 'R', sequence, raw)
        with self.assertRaises(KeyError):
            append(self.book, 'unknown', 2, 9)
        append(self.book, 'R', 2, 5)
        self.assertEqual(seal(self.book, self.originals, 'R').samples, (Sample(1, 4), Sample(2, 5)))

    def test_empty_seal(self):
        self.open_run()
        with self.assertRaises(ValueError):
            seal(self.book, self.originals, 'R')
        with self.assertRaises(KeyError):
            self.originals.get('R')
        self.assertEqual(self.device.active_recording, 'R')
        append(self.book, 'R', 1, 13)
        self.assertEqual(seal(self.book, self.originals, 'R').samples, (Sample(1, 13),))

    def test_stop_with_active(self):
        self.open_run()
        with self.assertRaises(ValueError):
            seal(self.book, self.originals, 'R')
        with self.assertRaises(RuntimeError):
            stop(self.device)
        self.assertEqual(self.device.mode, DeviceMode.RUNNING)
        append(self.book, 'R', 1, 13)
        seal(self.book, self.originals, 'R')
        self.assertEqual(self.device.mode, DeviceMode.RUNNING)
        stop(self.device)
        self.assertEqual(self.device.mode, DeviceMode.STOPPED)
