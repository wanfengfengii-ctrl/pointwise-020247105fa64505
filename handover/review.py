from collections.abc import Iterable

from archive.reports import Report, ReportStore
from rules.validate import require_label


def review_reports(
    reports: ReportStore, shift_id: str, report_ids: Iterable[str],
) -> tuple[Report, ...]:
    require_label(shift_id, 'shift id')
    if isinstance(report_ids, (str, bytes)):
        raise ValueError('report references must be a collection')
    reviewed = []
    seen_recordings: set[tuple[str, str]] = set()
    for report_id in report_ids:
        report = reports.get_report(report_id)
        original = report.original
        if original.shift_id != shift_id:
            raise ValueError(f'report {report_id!r} belongs to another shift')
        key = (original.device_id, original.recording_id)
        if key in seen_recordings:
            raise ValueError(f'duplicate recording in report {report_id!r}')
        seen_recordings.add(key)
        reviewed.append(report)
    return tuple(reviewed)
