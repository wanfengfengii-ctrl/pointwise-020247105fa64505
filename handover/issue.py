from collections.abc import Iterable

from archive.reports import ReportStore
from handover.notes import HandoverNote, HandoverNoteStore
from handover.review import review_reports
from handover.summary import summarize_shift


def issue(
    reports: ReportStore, notes: HandoverNoteStore, shift_id: str, report_ids: Iterable[str],
) -> HandoverNote:
    reviewed = review_reports(reports, shift_id, report_ids)
    return notes.save(summarize_shift(shift_id, reviewed))
