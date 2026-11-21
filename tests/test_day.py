import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from demo import DEFAULT_INPUT, run_day


class DayWorkflowTests(unittest.TestCase):
    def test_day_workflow(self):
        scenario = json.loads(DEFAULT_INPUT.read_text(encoding='utf-8'))
        with TemporaryDirectory(prefix='chengwan-workflow-') as directory:
            result = run_day(Path(directory) / 'station.sqlite3', scenario)
        expected_reports = [
            {'device_id': 'CW-01', 'recording_id': 'A', 'shift_id': '早班', 'rule_id': 'K',
             'revision_id': 'J1', 'scale_mm_per_s_per_code': '1', 'threshold_mm_per_s': '10',
             'waveform': [[1, -7], [2, 11]], 'peak_mm_per_s': '11', 'peak_sequence': 2,
             'exceeded': True},
            {'device_id': 'CW-01', 'recording_id': 'B', 'shift_id': '早班', 'rule_id': 'K',
             'revision_id': 'J2', 'scale_mm_per_s_per_code': '2', 'threshold_mm_per_s': '10',
             'waveform': [[1, -5], [2, 5]], 'peak_mm_per_s': '10', 'peak_sequence': 1,
             'exceeded': False},
        ]
        report_ids = [report['report_id'] for report in result['reports']]
        receipt_ids = [report['receipt_id'] for report in result['reports']]
        actual_reports = [
            {key: value for key, value in report.items() if key not in ('report_id', 'receipt_id')}
            for report in result['reports']
        ]
        expected_downstream = {
            'device_mode': 'offline', 'shift_id': '早班', 'report_ids': report_ids,
            'exceeded_count': 1,
            'discard': {'recording_id': 'C', 'reason': '夹具松脱', 'archive_rejected': True},
        }
        actual_downstream = {
            'device_mode': result['device_mode'], 'shift_id': result['handover']['shift_id'],
            'report_ids': result['handover']['report_ids'],
            'exceeded_count': result['handover']['exceeded_count'], 'discard': result['discard'],
        }
        self.assertEqual(actual_reports, expected_reports)
        self.assertEqual(actual_downstream, expected_downstream)
        self.assertEqual(len(set(report_ids + receipt_ids + [result['handover']['handover_id']])), 5)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v9.offline_evidence', 'input': scenario,
            'expected': expected_reports, 'actual': actual_reports,
            'downstream_expected': expected_downstream, 'downstream_actual': actual_downstream,
            'code_paths': ['record/seal.py', 'archive/calibrate.py', 'archive/peak.py',
                           'archive/commit.py', 'archive/reports.py', 'maintenance/discard.py',
                           'handover/summary.py', 'handover/lookup.py'],
            'oracle': '手算 A 的绝对值为 7、11，B 为 10、10。取首次最大值，仅 A 严格超过 10。交班引用必须与实际签发的两份报告一致。',
        }, ensure_ascii=False, sort_keys=True))

    def test_demo_failure_exit_code(self):
        with TemporaryDirectory(prefix='chengwan-invalid-') as directory:
            invalid = Path(directory) / 'invalid.json'
            scenario = json.loads(DEFAULT_INPUT.read_text(encoding='utf-8'))
            scenario['recordings'][0]['codes'] = []
            invalid.write_text(json.dumps(scenario), encoding='utf-8')
            completed = subprocess.run(
                [sys.executable, '-B', '-m', 'demo', '--input', str(invalid)],
                cwd=DEFAULT_INPUT.parent.parent, capture_output=True, text=True, check=False, timeout=20,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn('cannot seal an empty recording', completed.stderr)
        self.assertEqual(completed.stdout, '')
