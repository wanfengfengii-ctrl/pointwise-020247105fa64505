from dataclasses import dataclass

from archive.reports import Report


@dataclass(frozen=True, slots=True)
class ShiftSummary:
    shift_id: str
    report_ids: tuple[str, ...]
    exceeded_count: int


def summarize_shift(shift_id: str, reviewed: tuple[Report, ...]) -> ShiftSummary:
    references = tuple(sorted(report.report_id for report in reviewed))
    exceeded = sum(report.peak.exceeded for report in reviewed)
    return ShiftSummary(shift_id, references, exceeded)
