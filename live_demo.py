"""不停采作废与实收链路演示。

按 LIVE.md 的可控交接样例，在台架继续录制期间展示设备侧一次裁决：
夹具松脱的废测（原码 -7、11）不会入账；获准归档的同样波形在站库一次
提交失败后重开续办，凭同一首执查到峰值 11 mm/s，设备随后释放原件，
停源重开仍可追溯。
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.intake import archive_live
from archive.reports import ReportStore
from archive.storage import open_station
from maintenance.history import DiscardHistory
from record.mode import DeviceState, stop
from record.runs import RunBook, append, open as open_recording
from record.seal import SealedStore, seal
from record.source import RecordingSource
from rules.register import register
from rules.revisions import RevisionRegistry


def _live_port(device, originals, connection):
    history = DiscardHistory(connection)
    return history, RecordingSource(device, originals, history.find, live=True)


def run_live(database: Path) -> dict:
    registry = RevisionRegistry()
    register(registry, 'K', 'J1', 1, 10)
    device = DeviceState('CW-02')
    book = RunBook(device)
    originals = SealedStore()

    # R 封定后 S 立即开测，台架保持运行态。
    open_recording(book, registry, 'R', '早班', 'K', 'J1')
    append(book, 'R', 1, -7)
    append(book, 'R', 2, 11)
    seal(book, originals, 'R')
    open_recording(book, registry, 'S', '早班', 'K', 'J1')
    append(book, 'S', 1, -7)
    append(book, 'S', 2, 11)
    seal(book, originals, 'S')
    open_recording(book, registry, 'T', '早班', 'K', 'J1')
    append(book, 'T', 1, 6)

    with open_station(database) as connection:
        history, port = _live_port(device, originals, connection)
        reports = ReportStore(connection)

        # 裁决一：现场作废胜出，废测不产生报告或首执，下一测次继续。
        discard_verdict = port.discard_live('R', '夹具松脱')
        discarded_status, _ = archive_live(port, reports, 'R')
        append(book, 'T', 2, -4)
        seal(book, originals, 'T')

        # 裁决二：归档资格胜出，现场再请求作废只得到 claimed。
        port.claim_archive('S')
        later_discard = port.discard_live('S', '夹具松脱')

        # 让站库第一次提交失败（触发器回滚首执写入）。
        connection.execute('''
            CREATE TEMP TRIGGER fail_demo_receipt BEFORE INSERT ON receipts
            WHEN EXISTS (SELECT 1 FROM reports WHERE report_key = NEW.report_key)
            BEGIN
                SELECT RAISE(ABORT, 'demo receipt write failed');
            END
        ''')
        first_attempt = archive_live(port, reports, 'S')
        connection.execute('DROP TRIGGER fail_demo_receipt')
        retained_after_failure = originals.get('S') is not None

    # 重开站库，按原裁决续办并补交实收确认，复领同一首执。
    with open_station(database) as connection:
        reports = ReportStore(connection)
        _, port = _live_port(device, originals, connection)
        status, signed = archive_live(port, reports, 'S')
        receipt_id = signed.receipt_id
        try:
            originals.get('S')
        except KeyError:
            released = True
        else:
            released = False
        # 重投沿用同一份已签结果。
        replay_status, replayed = archive_live(port, reports, 'S')
        assert replayed == signed

        stop(device)
        device.power_off()

    # 停源后再开站库，仅凭首执追溯原据与峰值。
    with open_station(database) as connection:
        reports = ReportStore(connection)
        recalled = reports.get_by_receipt(receipt_id)
        report = recalled.report
        return {
            'device_id': 'CW-02',
            'discarded': {
                'recording_id': 'R',
                'reason': '夹具松脱',
                'device_verdict': discard_verdict,
                'station_status': discarded_status,
                'report_present': reports.find_by_recording('CW-02', 'R') is not None,
            },
            'archived': {
                'recording_id': 'S',
                'claim_won_over_later_discard': later_discard,
                'first_attempt': first_attempt,
                'retained_after_failure': retained_after_failure,
                'retry_status': status,
                'receipt_id': receipt_id,
                'replay_status': replay_status,
                'waveform': [[s.sequence, s.raw] for s in report.original.samples],
                'origin': {
                    'device_id': report.original.device_id,
                    'shift_id': report.original.shift_id,
                    'rule_id': report.original.rule.rule_id,
                    'revision_id': report.original.rule.revision_id,
                },
                'peak_mm_per_s': str(report.peak.magnitude),
                'peak_sequence': report.peak.sequence,
                'exceeded': report.peak.exceeded,
                'device_released_original': released,
            },
            'next_recording_kept_capturing': True,
            'device_mode': device.mode.value,
        }


def main() -> int:
    with TemporaryDirectory(prefix='chengwan-live-demo-') as directory:
        result = run_live(Path(directory) / 'station.sqlite3')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
