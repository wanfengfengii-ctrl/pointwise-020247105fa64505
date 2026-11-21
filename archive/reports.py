from dataclasses import dataclass
from fractions import Fraction
import json
import sqlite3

from archive.peak import PeakResult
from archive.storage import reference_for, reference_key
from record.samples import Sample
from record.seal import SealedOriginal
from rules.freeze import FrozenRule


@dataclass(frozen=True, slots=True)
class OriginalEvidence:
    device_id: str
    recording_id: str
    shift_id: str
    rule: FrozenRule
    samples: tuple[Sample, ...]

    @classmethod
    def from_original(cls, original: SealedOriginal) -> 'OriginalEvidence':
        return cls(
            original.device_id, original.recording_id, original.shift_id,
            original.rule, original.samples,
        )


@dataclass(frozen=True, slots=True)
class Report:
    report_id: str
    original: OriginalEvidence
    peak: PeakResult


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    report: Report
    receipt_id: str


def _fraction_parts(value: Fraction) -> tuple[str, str]:
    return format(value.numerator, 'x'), format(value.denominator, 'x')


def _fraction_from(row: sqlite3.Row, name: str) -> Fraction:
    return Fraction(int(row[f'{name}_num'], 16), int(row[f'{name}_den'], 16))


def _signed_result(row: sqlite3.Row) -> ArchiveResult:
    rule = FrozenRule(
        row['rule_id'], row['revision_id'], _fraction_from(row, 'scale'),
        _fraction_from(row, 'threshold'),
    )
    samples = tuple(Sample(sequence, int(raw, 16)) for sequence, raw in json.loads(row['waveform']))
    original = OriginalEvidence(row['device_id'], row['recording_id'], row['shift_id'], rule, samples)
    peak = PeakResult(_fraction_from(row, 'peak'), row['peak_sequence'], bool(row['exceeded']))
    report = Report(reference_for('report', row['report_key']), original, peak)
    return ArchiveResult(report, reference_for('receipt', row['report_key']))


class ReportStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def find_by_recording(self, device_id: str, recording_id: str) -> ArchiveResult | None:
        row = self.connection.execute('''
            SELECT reports.* FROM reports JOIN receipts USING (report_key)
            WHERE device_id = ? AND recording_id = ?
        ''', (device_id, recording_id)).fetchone()
        return _signed_result(row) if row is not None else None

    def _get_signed(self, report_key: int, reference: str) -> ArchiveResult:
        row = self.connection.execute('''
            SELECT reports.* FROM reports JOIN receipts USING (report_key)
            WHERE report_key = ?
        ''', (report_key,)).fetchone()
        if row is None:
            raise KeyError(reference)
        return _signed_result(row)

    def get_report(self, report_id: str) -> Report:
        return self._get_signed(reference_key(report_id, 'report'), report_id).report

    def get_by_receipt(self, receipt_id: str) -> ArchiveResult:
        return self._get_signed(reference_key(receipt_id, 'receipt'), receipt_id)

    def write_report(self, original: OriginalEvidence, peak: PeakResult) -> Report:
        if not self.connection.in_transaction:
            raise RuntimeError('report writes require a station transaction')
        rule = original.rule
        waveform = json.dumps(
            [(sample.sequence, format(sample.raw, 'x')) for sample in original.samples],
            separators=(',', ':'),
        )
        cursor = self.connection.execute('''
            INSERT INTO reports (
                device_id, recording_id, shift_id, rule_id, revision_id,
                scale_num, scale_den, threshold_num, threshold_den, waveform,
                peak_num, peak_den, peak_sequence, exceeded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            original.device_id, original.recording_id, original.shift_id, rule.rule_id,
            rule.revision_id, *_fraction_parts(rule.scale), *_fraction_parts(rule.threshold),
            waveform, *_fraction_parts(peak.magnitude), peak.sequence, int(peak.exceeded),
        ))
        return Report(reference_for('report', cursor.lastrowid), original, peak)

    def write_receipt(self, report: Report) -> ArchiveResult:
        if not self.connection.in_transaction:
            raise RuntimeError('receipt writes require a station transaction')
        report_key = reference_key(report.report_id, 'report')
        self.connection.execute('INSERT INTO receipts (report_key) VALUES (?)', (report_key,))
        return ArchiveResult(report, reference_for('receipt', report_key))
