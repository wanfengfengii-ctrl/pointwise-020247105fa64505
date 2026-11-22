import unittest
from dataclasses import replace
from fractions import Fraction

from archive.intake import archive
from archive.peak import PeakResult
from handover.lookup import lookup
from maintenance.discard import discard
from maintenance.history import DiscardHistory
from maintenance.session import maintenance
from record.mode import stop
from record.rulings import ArchiveClaim
from record.runs import append, open as open_recording
from record.samples import Sample
from record.seal import seal
from record.source import DiscardedOriginal
from tests.rig import StationRig


class LiveDiscardTests(unittest.TestCase):
    def setUp(self):
        self.rig = StationRig(self)
        self.rig.register()
        self.port = self.rig.live_source()

    def test_discard_wins_while_capture_continues(self):
        self.rig.record('R', [-7, 11])
        open_recording(self.rig.book, self.rig.registry, 'S', 'early', 'K', 'J1')
        self.assertEqual(self.port.discard_live('R', '夹具松脱'), 'discarded')
        # The bench never stops: the next source sequence is still accepted.
        append(self.rig.book, 'S', 1, 5)
        append(self.rig.book, 'S', 2, -9)
        seal(self.rig.book, self.rig.originals, 'S')

        self.assertEqual(self.rig.ruling_state('R'), 'discarded')
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        with self.assertRaises(DiscardedOriginal):
            self.port.read_original('R')
        self.assertIsNone(self.port.claim_archive('R'))

        status, result = self.rig.archive_live(self.port, 'R')
        self.assertEqual((status, result), ('discarded', None))
        # No report and no receipt are ever produced for the discarded codes.
        self.assertIsNone(self.rig.reports.find_by_recording('bench-4', 'R'))
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))

        # Replaying the discard keeps the original single verdict and reason.
        self.assertEqual(self.port.discard_live('R', '电缆折损'), 'discarded')
        self.assertEqual(self.rig.ruling_state('R'), 'discarded')
        # The other, intact recording still archives normally.
        status, signed = self.rig.archive_live(self.port, 'S')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak, PeakResult(Fraction(9), 2, False))

    def test_discard_verdict_survives_station_reopen(self):
        self.rig.record('R', [-7, 11])
        self.assertEqual(self.port.discard_live('R', '夹具松脱'), 'discarded')
        self.rig.reopen()
        port = self.rig.live_source()
        self.assertEqual(port.discard_live('R', '夹具松脱'), 'discarded')
        self.assertEqual(self.rig.archive_live(port, 'R'), ('discarded', None))
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))

    def test_adjudication_works_with_station_closed(self):
        self.rig.record('R', [-7, 11])
        # Detach the SQLite connection entirely; device verdicts are local.
        self.rig._station.close()
        try:
            self.assertEqual(self.port.discard_live('R', '夹具松脱'), 'discarded')
            self.rig.record('T', [8])
            claim = self.port.claim_archive('T')
            self.assertIsInstance(claim, ArchiveClaim)
            self.assertEqual(self.port.discard_live('T', 'x'), 'claimed')
        finally:
            self.rig.reopen()
        self.assertEqual(self.rig.archive_live(self.rig.live_source(), 'R'),
                         ('discarded', None))

    def test_live_switch_must_be_boolean(self):
        from record.source import RecordingSource
        with self.assertRaises(ValueError):
            RecordingSource(self.rig.device, self.rig.originals,
                            self.rig._find_discard, live='yes')

    def test_live_discard_requires_running_device(self):
        self.rig.record('R', [-7, 11])
        stop(self.rig.device)
        with self.assertRaises(RuntimeError):
            self.port.discard_live('R', '夹具松脱')
        maintenance(self.rig.device, True)
        with self.assertRaises(RuntimeError):
            self.port.discard_live('R', '夹具松脱')
        maintenance(self.rig.device, False)
        # Illegal reasons are only reached when the device is running.
        open_recording(self.rig.book, self.rig.registry, 'Q', 'early', 'K', 'J1')
        with self.assertRaises(ValueError):
            self.port.discard_live('R', '   ')

    def test_unknown_or_unsealed_live_targets(self):
        open_recording(self.rig.book, self.rig.registry, 'open', 'early', 'K', 'J1')
        with self.assertRaises(KeyError):
            self.port.discard_live('missing', '夹具松脱')
        with self.assertRaises(KeyError):
            self.port.claim_archive('missing')
        with self.assertRaises(KeyError):
            self.port.discard_live('open', '夹具松脱')
        with self.assertRaises(KeyError):
            self.port.claim_archive('open')

    def test_non_live_port_rejects_live_entries(self):
        self.rig.record('R', [-7, 11])
        with self.assertRaises(RuntimeError):
            self.rig.source.discard_live('R', '夹具松脱')
        with self.assertRaises(RuntimeError):
            self.rig.source.claim_archive('R')
        with self.assertRaises(RuntimeError):
            self.rig.source.confirm_archive(object())

    def test_maintenance_recognizes_live_discard(self):
        self.rig.record('R', [-7, 11])
        self.assertEqual(self.port.discard_live('R', '夹具松脱'), 'discarded')
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        # Same reason replay is accepted, a different reason is refused.
        self.assertEqual(discard(
            self.rig.device, self.rig.originals, self.rig.history, 'R', '夹具松脱',
        ).reason, '夹具松脱')
        with self.assertRaisesRegex(ValueError, 'conflicting discard reason'):
            discard(self.rig.device, self.rig.originals, self.rig.history, 'R', '电缆折损')
        maintenance(self.rig.device, False)
        self.assertEqual(DiscardHistory(self.rig.connection).find('bench-4', 'R').reason,
                         '夹具松脱')
        with self.assertRaises(DiscardedOriginal):
            archive(self.rig.source, self.rig.reports, 'R')

    def test_maintenance_discard_blocks_live_and_archive_after_resume(self):
        self.rig.record('M', [3])
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        discard(self.rig.device, self.rig.originals, self.rig.history, 'M', '定位销歪斜')
        maintenance(self.rig.device, False)
        # Resume capturing; the maintenance fact must keep blocking bypasses.
        self.rig.record('N', [4])
        port = self.rig.live_source()
        with self.assertRaises(DiscardedOriginal):
            port.read_original('M')
        self.assertIsNone(port.claim_archive('M'))
        self.assertEqual(self.rig.archive_live(port, 'M'), ('discarded', None))
        self.assertEqual(self.rig.ruling_state('M'), 'discarded')

    def test_maintenance_fact_keeps_blocking_after_station_reopen(self):
        self.rig.record('M', [3])
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        discard(self.rig.device, self.rig.originals, self.rig.history, 'M', '定位销歪斜')
        maintenance(self.rig.device, False)
        self.rig.reopen()
        port = self.rig.live_source()
        self.assertEqual(self.rig.archive_live(port, 'M'), ('discarded', None))
        with self.assertRaises(DiscardedOriginal):
            archive(self.rig.source, self.rig.reports, 'M')
        self.assertIsNone(self.rig.reports.find_by_recording('bench-4', 'M'))


class LiveClaimTests(unittest.TestCase):
    def setUp(self):
        self.rig = StationRig(self)
        self.rig.register()
        self.port = self.rig.live_source()

    def test_claim_wins_and_releases_after_receipt(self):
        original = self.rig.record('R', [-7, 11])
        open_recording(self.rig.book, self.rig.registry, 'S', 'early', 'K', 'J1')
        claim = self.port.claim_archive('R')
        self.assertIsInstance(claim, ArchiveClaim)
        self.assertTrue(claim.matches(original))
        self.assertIs(self.port.claim_archive('R'), claim)
        self.assertEqual(self.port.discard_live('R', '夹具松脱'), 'claimed')
        # The device stays in custody until the station acknowledges receipt.
        self.assertIs(self.rig.originals.get('R'), original)
        # Meanwhile the next test keeps recording.
        append(self.rig.book, 'S', 1, 6)

        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak, PeakResult(Fraction(11), 2, True))
        self.assertEqual(signed.report.original.samples, (Sample(1, -7), Sample(2, 11)))
        # Acknowledgement releases the device-held waveform.
        self.assertFalse(self.rig.holds_original('R'))
        with self.assertRaises(KeyError):
            self.rig.originals.get('R')
        with self.assertRaises(KeyError):
            self.port.read_original('R')
        self.assertEqual(self.rig.ruling_state('R'), 'released')

        # The old qualification remains obtainable and verifiable afterwards.
        same = self.port.claim_archive('R')
        self.assertEqual(same, claim)
        self.assertTrue(same.matches(signed.report.original))

        seal(self.rig.book, self.rig.originals, 'S')

    def test_claim_accepted_in_stopped_mode(self):
        self.rig.record('R', [-7, 11])
        stop(self.rig.device)
        claim = self.port.claim_archive('R')
        self.assertIsInstance(claim, ArchiveClaim)
        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak.magnitude, 11)

    def test_claim_bound_identity_and_content(self):
        original = self.rig.record('R', [-7, 11])
        claim = self.port.claim_archive('R')
        # Same waveform content under another recording id must not match.
        other = self.rig.record('T', [-7, 11])
        self.assertFalse(claim.matches(other))
        # Same id with altered content, shift or rule binding is also rejected.
        tampered = replace(original, samples=(Sample(1, -7), Sample(2, 12)))
        self.assertFalse(claim.matches(tampered))
        shifted = replace(original, shift_id='late')
        self.assertFalse(claim.matches(shifted))
        self.assertTrue(claim.matches(original))

    def test_confirm_rejects_foreign_or_wrong_claim(self):
        self.rig.record('R', [-7, 11])
        self.rig.record('T', [5])
        claim_r = self.port.claim_archive('R')
        self.port.claim_archive('T')
        # A qualification whose binding was altered cannot confirm the device.
        forged = replace(claim_r, samples=((1, -7), (2, 999)))
        with self.assertRaises(ValueError):
            self.port.confirm_archive(forged)
        self.assertTrue(self.rig.holds_original('R'))
        with self.assertRaises(ValueError):
            self.port.confirm_archive(object())
        # An unknown recording's fabricated qualification is an identity error.
        fabricated = replace(claim_r, recording_id='ghost')
        with self.assertRaises(KeyError):
            self.port.confirm_archive(fabricated)
        self.port.confirm_archive(claim_r)
        # Replaying the same confirmation is idempotent.
        self.port.confirm_archive(claim_r)
        self.assertFalse(self.rig.holds_original('R'))
        self.assertTrue(self.rig.holds_original('T'))

    def test_claimed_recording_resists_maintenance_discard(self):
        self.rig.record('R', [-7, 11])
        self.assertIsInstance(self.port.claim_archive('R'), ArchiveClaim)
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        with self.assertRaisesRegex(ValueError, 'qualified for archiving'):
            discard(self.rig.device, self.rig.originals, self.rig.history, 'R', '夹具松脱')
        maintenance(self.rig.device, False)
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak.sequence, 2)

    def test_wrong_payload_is_refused_without_artefacts(self):
        self.rig.record('R', [-7, 11])
        other = self.rig.record('T', [29])
        self.port.claim_archive('R')

        def swap_read(received):
            # Hand back another recording's sealed waveform under R's request.
            return self.rig.originals.get('T')

        self.port.after['read_original'] = swap_read
        with self.assertRaisesRegex(ValueError, 'identity mismatch|does not match'):
            self.rig.archive_live(self.port, 'R')
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        self.assertEqual(self.rig.ruling_state('R'), 'claimed')
        self.assertTrue(self.rig.holds_original('R'))

        # Same recording id but altered waveform content is a wrong payload too.
        port = self.rig.live_source()
        original = self.rig.originals.get('R')
        port.after['read_original'] = lambda received: replace(
            original, samples=(Sample(1, -7), Sample(2, 99)),
        )
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.rig.archive_live(port, 'R')
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        self.assertTrue(self.rig.holds_original('R'))

    def test_qualification_obtained_after_reading_sealed_file(self):
        original = self.rig.record('R', [-7, 11])
        # Reading the sealed file alone does not grant qualification.
        self.assertIs(self.port.read_original('R'), original)
        self.assertEqual(self.rig.ruling_state('R'), None)
        claim = self.port.claim_archive('R')
        self.assertTrue(claim.matches(original))
        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak.magnitude, 11)

    def test_discard_interleaving_before_qualification(self):
        self.rig.record('R', [-7, 11])

        def discard_during_claim(recording_id):
            self.port.port.discard_live(recording_id, '夹具松脱')

        self.port.before['claim_archive'] = discard_during_claim
        self.assertEqual(self.rig.archive_live(self.port, 'R'), ('discarded', None))
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        self.assertEqual(self.rig.ruling_state('R'), 'discarded')
        self.assertEqual(self.port.calls, ['claim_archive'])


class LiveFailureTests(unittest.TestCase):
    def setUp(self):
        self.rig = StationRig(self)
        self.rig.register()
        self.port = self.rig.live_source()

    def test_commit_failure_returns_retry_with_no_artefacts(self):
        original = self.rig.record('R', [-7, 11])
        self.rig.reject_receipt_writes()
        self.assertEqual(self.rig.archive_live(self.port, 'R'), ('retry', None))
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        self.assertTrue(self.rig.holds_original('R'))
        self.assertEqual(self.rig.ruling_state('R'), 'claimed')

        self.rig.reopen()
        port = self.rig.live_source()
        status, signed = self.rig.archive_live(port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak, PeakResult(Fraction(11), 2, True))
        self.assertEqual(self.rig.counts()[:3], (1, 1, 0))
        self.assertFalse(self.rig.holds_original('R'))
        self.assertIsNotNone(original)

    def test_sqlite_commit_denial_is_retryable(self):
        self.rig.record('R', [-7, 11])
        self.rig.reject_next_commit()
        self.assertEqual(self.rig.archive_live(self.port, 'R'), ('retry', None))
        self.assertEqual(self.rig.denied_commits, 1)
        self.assertTrue(self.rig.holds_original('R'))
        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak.sequence, 2)

    def test_transport_failure_before_read_is_retryable(self):
        self.rig.record('R', [-7, 11])

        def fail_claim(recording_id):
            raise OSError('link down')

        self.port.before['claim_archive'] = fail_claim
        self.assertEqual(self.rig.archive_live(self.port, 'R'), ('retry', None))
        self.assertEqual(self.rig.counts()[:3], (0, 0, 0))
        self.assertEqual(self.rig.ruling_state('R'), None)
        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak.magnitude, 11)

    def test_lost_confirmation_after_commit_is_completed_after_reopen(self):
        self.rig.record('R', [-7, 11])
        # The station commits, but the acknowledgement transport fails before
        # the device gets it: the device keeps custody of the waveform.
        def fail_confirm(claim):
            raise OSError('ack lost')

        self.port.before['confirm_archive'] = fail_confirm
        self.assertEqual(self.rig.archive_live(self.port, 'R'), ('retry', None))
        self.assertTrue(self.rig.holds_original('R'))
        receipt_id = self.rig.reports.find_by_recording('bench-4', 'R').receipt_id

        self.rig.reopen()
        port = self.rig.live_source()
        status, signed = self.rig.archive_live(port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.receipt_id, receipt_id)
        self.assertFalse(self.rig.holds_original('R'))
        # A second replay still returns the same single signed result.
        status, again = self.rig.archive_live(port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(again, signed)

    def test_confirmation_completed_before_answer_was_lost(self):
        self.rig.record('R', [-7, 11])
        # The device already released the original; only the answer vanished.
        def release_then_fail(result):
            self.assertFalse(self.rig.holds_original('R'))
            raise OSError('answer lost')

        self.port.after['confirm_archive'] = release_then_fail
        self.assertEqual(self.rig.archive_live(self.port, 'R'), ('retry', None))
        self.rig.reopen()
        port = self.rig.live_source()
        status, signed = self.rig.archive_live(port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(signed.report.peak, PeakResult(Fraction(11), 2, True))
        self.assertFalse(self.rig.holds_original('R'))

    def test_persisted_original_used_when_device_already_released(self):
        self.rig.record('R', [-7, 11])
        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        self.assertFalse(self.rig.holds_original('R'))
        # Reopen with a fresh port: the replay must not ask the device for the
        # released waveform, but still re-check the claim against persistence.
        self.rig.reopen()
        port = self.rig.live_source()
        port.before['read_original'] = lambda recording_id: (_ for _ in ()).throw(
            AssertionError('station must not reread a released waveform'))
        status, replayed = self.rig.archive_live(port, 'R')
        self.assertEqual(status, 'signed')
        self.assertEqual(replayed, signed)

    def test_offline_lookup_still_finds_peak_after_power_off(self):
        self.rig.record('R', [-7, 11])
        status, signed = self.rig.archive_live(self.port, 'R')
        self.assertEqual(status, 'signed')
        stop(self.rig.device)
        self.rig.device.power_off()
        self.rig.reopen()
        recalled = lookup(self.rig.reports, self.rig.notes, signed.receipt_id)
        self.assertEqual(recalled, signed)
        self.assertEqual(recalled.report.peak, PeakResult(Fraction(11), 2, True))
        self.assertEqual(recalled.report.original.samples, (Sample(1, -7), Sample(2, 11)))
        with self.assertRaises(RuntimeError):
            self.rig.live_source().read_original('R')

    def test_mode_guards_for_live_archive(self):
        self.rig.record('R', [-7, 11])
        stop(self.rig.device)
        maintenance(self.rig.device, True)
        with self.assertRaises(RuntimeError):
            self.rig.archive_live(self.port, 'R')
        maintenance(self.rig.device, False)
        self.rig.device.power_off()
        with self.assertRaises(RuntimeError):
            self.rig.archive_live(self.port, 'R')

    def test_legacy_archive_obeys_live_verdicts(self):
        self.rig.record('R', [-7, 11])
        self.port.discard_live('R', '夹具松脱')
        stop(self.rig.device)
        with self.assertRaises(DiscardedOriginal):
            archive(self.rig.source, self.rig.reports, 'R')

        self.rig.record('T', [12])
        stop(self.rig.device)
        # A claimed, non-discarded recording still works through the old path.
        live = self.rig.live_source()
        self.assertIsInstance(live.claim_archive('T'), ArchiveClaim)
        signed = archive(self.rig.source, self.rig.reports, 'T')
        self.assertEqual(signed.report.peak.magnitude, 12)

    def test_legacy_archive_then_live_confirm_releases_original(self):
        # Qualification via the live port, signing via the stopped legacy path:
        # the live confirmation still releases the device-held waveform.
        self.rig.record('R', [-7, 11])
        claim = self.port.claim_archive('R')
        stop(self.rig.device)
        signed = archive(self.rig.source, self.rig.reports, 'R')
        self.assertTrue(self.rig.holds_original('R'))
        port = self.rig.live_source()
        port.confirm_archive(claim)
        self.assertFalse(self.rig.holds_original('R'))
        self.assertEqual(self.rig.reports.get_by_receipt(signed.receipt_id), signed)
