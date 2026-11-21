from fractions import Fraction
from typing import Protocol

from archive.calibrate import calibrate
from archive.commit import commit_report
from archive.peak import find_peak
from archive.reports import ArchiveResult, ReportStore
from record.mode import DeviceMode
from record.samples import Sample, validate_sample
from record.seal import SealedOriginal
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
