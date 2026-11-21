import argparse
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from archive.intake import archive
from archive.reports import ArchiveResult, ReportStore
from archive.storage import open_station
from handover.issue import issue
from handover.lookup import lookup
from handover.notes import HandoverNoteStore
from maintenance.discard import discard
from maintenance.history import DiscardHistory
from maintenance.session import maintenance
from record.mode import DeviceState, stop
from record.runs import RunBook, append, open as open_recording
from record.seal import SealedStore, seal
from record.source import DiscardedOriginal, RecordingSource
from rules.register import register
from rules.revisions import RevisionRegistry


DEFAULT_INPUT = Path(__file__).resolve().parent / 'samples' / 'day.json'


def _capture(book, originals, recording_id, codes):
    for sequence, raw in enumerate(codes, start=1):
        append(book, recording_id, sequence, raw)
    seal(book, originals, recording_id)


def _report_view(result: ArchiveResult) -> dict:
    report = result.report
    original = report.original
    return {
        'report_id': report.report_id,
        'receipt_id': result.receipt_id,
        'device_id': original.device_id,
        'recording_id': original.recording_id,
        'shift_id': original.shift_id,
        'rule_id': original.rule.rule_id,
        'revision_id': original.rule.revision_id,
        'scale_mm_per_s_per_code': str(original.rule.scale),
        'threshold_mm_per_s': str(original.rule.threshold),
        'waveform': [[sample.sequence, sample.raw] for sample in original.samples],
        'peak_mm_per_s': str(report.peak.magnitude),
        'peak_sequence': report.peak.sequence,
        'exceeded': report.peak.exceeded,
    }


def run_day(database: Path, scenario: dict) -> dict:
    registry = RevisionRegistry()
    device = DeviceState(scenario['device_id'])
    book = RunBook(device)
    originals = SealedStore()
    rule_id = scenario['rule_id']
    shift_id = scenario['shift_id']
    first, *later = scenario['recordings']
    register(registry, rule_id, **scenario['initial_rule'])
    open_recording(book, registry, first['recording_id'], shift_id, rule_id, first['revision_id'])
    register(registry, rule_id, **scenario['next_rule'])
    _capture(book, originals, first['recording_id'], first['codes'])
    for row in later:
        open_recording(book, registry, row['recording_id'], shift_id, rule_id, row['revision_id'])
        _capture(book, originals, row['recording_id'], row['codes'])
    stop(device)

    discarded_id = scenario['discard']['recording_id']
    with open_station(database) as connection:
        history = DiscardHistory(connection)
        records = ReportStore(connection)
        notes = HandoverNoteStore(connection)
        source = RecordingSource(device, originals, history.find)
        signed = []
        for row in scenario['recordings']:
            if row['recording_id'] != discarded_id:
                signed.append(archive(source, records, row['recording_id']))
        note = issue(records, notes, shift_id, (result.report.report_id for result in signed))
        maintenance(device, True)
        discard(device, originals, history, discarded_id, scenario['discard']['reason'])
        maintenance(device, False)
        try:
            archive(source, records, discarded_id)
        except DiscardedOriginal:
            pass
        else:
            raise RuntimeError('discarded original was accepted by the station')
        device.power_off()

    with open_station(database) as connection:
        records = ReportStore(connection)
        notes = HandoverNoteStore(connection)
        saved = lookup(records, notes, note.handover_id)
        report_views = [_report_view(lookup(records, notes, result.receipt_id)) for result in signed]
        fact = DiscardHistory(connection).find(device.device_id, discarded_id)
        if fact is None:
            raise RuntimeError('discard history is missing after reopening')
        return {
            'device_mode': device.mode.value,
            'reports': report_views,
            'handover': {
                'handover_id': saved.handover_id,
                'shift_id': saved.shift_id,
                'report_ids': list(saved.report_ids),
                'exceeded_count': saved.exceeded_count,
            },
            'discard': {
                'recording_id': fact.recording_id,
                'reason': fact.reason,
                'archive_rejected': True,
            },
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='运行澄湾港区振动试验站早班样例')
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args(argv)
    try:
        scenario = json.loads(args.input.read_text(encoding='utf-8'))
        with TemporaryDirectory(prefix='chengwan-day-') as directory:
            result = run_day(Path(directory) / 'station.sqlite3', scenario)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error) as exc:
        print(f'振动试验站演示失败：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
