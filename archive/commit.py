import sqlite3

from archive.peak import PeakResult
from archive.reports import ArchiveResult, OriginalEvidence, ReportStore
from archive.storage import station_transaction
from record.seal import SealedOriginal


class ArchiveWriteError(RuntimeError):
    pass


def commit_report(
    reports: ReportStore, original: SealedOriginal, peak: PeakResult,
) -> ArchiveResult:
    evidence = OriginalEvidence.from_original(original)
    try:
        with station_transaction(reports.connection):
            existing = reports.find_by_recording(original.device_id, original.recording_id)
            if existing is not None:
                if existing.report.original != evidence:
                    raise ValueError('recording was signed with different original evidence')
                return existing
            report = reports.write_report(evidence, peak)
            return reports.write_receipt(report)
    except sqlite3.Error as exc:
        raise ArchiveWriteError(f'could not commit recording {original.recording_id!r}') from exc
