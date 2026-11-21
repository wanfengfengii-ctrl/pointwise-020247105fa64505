from archive.reports import ArchiveResult, ReportStore
from handover.notes import HandoverNote, HandoverNoteStore


def lookup(
    reports: ReportStore, notes: HandoverNoteStore, reference: str,
) -> ArchiveResult | HandoverNote:
    if isinstance(reference, str) and reference.startswith('receipt-'):
        return reports.get_by_receipt(reference)
    if isinstance(reference, str) and reference.startswith('handover-'):
        return notes.get(reference)
    raise KeyError(reference)
