from fractions import Fraction
from typing import Protocol

from archive.calibrate import calibrate
from archive.commit import ArchiveWriteError, commit_report
from archive.peak import find_peak
from archive.reports import ArchiveResult, ReportStore
from record.mode import DeviceMode
from record.rulings import ArchiveClaim
from record.samples import Sample, validate_sample
from record.seal import SealedOriginal
from record.source import DiscardedOriginal
from rules.freeze import FrozenRule
from rules.validate import require_label, validate_rule_parameters


class OriginalSource(Protocol):
    @property
    def device_id(self) -> str:
        ...

    def current_mode(self) -> DeviceMode:
        ...

    def read_original(self, recording_id: str) -> SealedOriginal:
        ...


class LiveOriginalSource(OriginalSource, Protocol):
    def claim_archive(self, recording_id: str) -> ArchiveClaim | None:
        ...

    def confirm_archive(self, claim: ArchiveClaim) -> None:
        ...


def verify_original(original: SealedOriginal, device_id: str, recording_id: str) -> None:
    if not isinstance(original, SealedOriginal):
        raise ValueError('expected a sealed original')
    if (original.device_id, original.recording_id) != (device_id, recording_id):
        raise ValueError('sealed original identity mismatch')
    require_label(original.shift_id, 'shift id')
    rule = original.rule
    if not isinstance(rule, FrozenRule):
        raise ValueError('sealed original requires a frozen rule')
    if not isinstance(rule.scale, Fraction) or not isinstance(rule.threshold, Fraction):
        raise ValueError('frozen rule must contain exact fractions')
    validate_rule_parameters(rule.rule_id, rule.revision_id, rule.scale, rule.threshold)
    if type(original.samples) is not tuple or not original.samples:
        raise ValueError('expected a nonempty sealed waveform')
    for expected, sample in enumerate(original.samples, start=1):
        if not isinstance(sample, Sample):
            raise ValueError('invalid sample in sealed waveform')
        validate_sample(sample.sequence, sample.raw, expected)


def archive(source: OriginalSource, reports: ReportStore, recording_id: str) -> ArchiveResult:
    require_label(recording_id, 'recording id')
    if source.current_mode() is not DeviceMode.STOPPED:
        raise RuntimeError('archive requires a stopped device')
    device_id = require_label(source.device_id, 'device id')
    existing = reports.find_by_recording(device_id, recording_id)
    if existing is not None:
        return existing
    original = source.read_original(recording_id)
    verify_original(original, device_id, recording_id)
    peak = find_peak(calibrate(original), original.rule.threshold)
    return commit_report(reports, original, peak)


def _reconfirm_persisted(
    source: LiveOriginalSource,
    reports: ReportStore,
    device_id: str,
    recording_id: str,
) -> tuple[str, ArchiveResult | None]:
    """Replay a recording whose report was already committed.

    The durable claim is re-checked against the persisted original evidence so
    a missing acknowledgement can be reissued without pulling the released
    waveform back from the device.
    """
    signed = reports.find_by_recording(device_id, recording_id)
    if signed is None:
        # The report vanished between the lookup and this helper; start over.
        return ('retry', None)
    claim = source.claim_archive(recording_id)
    if claim is None:
        return ('discarded', None)
    if not claim.matches(signed.report.original):
        raise ValueError('archive claim does not match the persisted sealed waveform')
    try:
        source.confirm_archive(claim)
    except OSError:
        return ('retry', None)
    return ('signed', signed)


def archive_live(
    source: LiveOriginalSource,
    reports: ReportStore,
    recording_id: str,
) -> tuple[str, ArchiveResult | None]:
    """Archive a sealed recording while the device may still be capturing.

    Returns ``('discarded', None)`` when the device verdict is discard,
    ``('retry', None)`` for a transient transport or commit failure with no
    new artefacts, and ``('signed', ArchiveResult)`` on success.
    """
    require_label(recording_id, 'recording id')
    if source.current_mode() not in (DeviceMode.RUNNING, DeviceMode.STOPPED):
        raise RuntimeError('live archive requires a running or stopped device')
    device_id = require_label(source.device_id, 'device id')

    if reports.find_by_recording(device_id, recording_id) is not None:
        return _reconfirm_persisted(source, reports, device_id, recording_id)

    # Bind the request to an exclusive qualification before touching the
    # waveform; the qualification may be obtained before or after read_original
    # in other call sequences, but here claiming first keeps the verdict stable
    # against a discard interleaving at any port boundary.
    try:
        claim = source.claim_archive(recording_id)
        if claim is None:
            return ('discarded', None)
        original = source.read_original(recording_id)
    except DiscardedOriginal:
        return ('discarded', None)
    except OSError:
        return ('retry', None)

    verify_original(original, device_id, recording_id)
    if not claim.matches(original):
        raise ValueError('archive claim does not match the supplied sealed waveform')

    peak = find_peak(calibrate(original), original.rule.threshold)
    try:
        signed = commit_report(reports, original, peak)
    except ArchiveWriteError:
        # Nothing was committed; the claim and the device-held waveform stay
        # usable for a later retry.
        return ('retry', None)

    # Only after the durable commit do we acknowledge the device.  A lost
    # answer here leaves the committed report discoverable and the confirmation
    # replayable after reopening the station.
    try:
        source.confirm_archive(claim)
    except OSError:
        return ('retry', None)
    return ('signed', signed)
