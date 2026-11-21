from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from archive.intake import archive
from archive.reports import ReportStore
from archive.storage import open_station
from handover.notes import HandoverNoteStore
from maintenance.history import DiscardHistory
from record.mode import DeviceMode, DeviceState
from record.runs import RunBook, append, open as open_recording
from record.seal import SealedOriginal, SealedStore, seal
from record.source import RecordingSource
from rules.register import register
from rules.revisions import RevisionRegistry


class ScheduledSource:
    def __init__(self, source: RecordingSource) -> None:
        self.source = source
        self.before_read: Callable[[str], None] | None = None
        self.after_read: Callable[[SealedOriginal], SealedOriginal | None] | None = None
        self.reads: list[str] = []

    @property
    def device_id(self) -> str:
        return self.source.device_id

    def current_mode(self) -> DeviceMode:
        return self.source.current_mode()

    def read_original(self, recording_id: str) -> SealedOriginal:
        before, self.before_read = self.before_read, None
        if before is not None:
            before(recording_id)
        original = self.source.read_original(recording_id)
        self.reads.append(recording_id)
        after, self.after_read = self.after_read, None
        if after is not None:
            replacement = after(original)
            if replacement is not None:
                return replacement
        return original


class StationRig:
    def __init__(self, case: unittest.TestCase) -> None:
        directory = TemporaryDirectory(prefix='chengwan-case-')
        case.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'station.sqlite3'
        self.device = DeviceState('bench-4')
        self.registry = RevisionRegistry()
        self.book = RunBook(self.device)
        self.originals = SealedStore()
        self._station = ExitStack()
        case.addCleanup(self._station.close)
        self.reopen()
        self.source = ScheduledSource(RecordingSource(self.device, self.originals, self._find_discard))
        self.denied_commits = 0

    def _find_discard(self, device_id: str, recording_id: str):
        return self.history.find(device_id, recording_id)

    def reopen(self) -> None:
        self._station.close()
        self.connection = self._station.enter_context(open_station(self.database))
        self.history = DiscardHistory(self.connection)
        self.reports = ReportStore(self.connection)
        self.notes = HandoverNoteStore(self.connection)

    def register(self, scale=1, threshold=10, revision_id='J1'):
        return register(self.registry, 'K', revision_id, scale, threshold)

    def record(self, recording_id, codes, *, shift_id='early', revision_id='J1') -> SealedOriginal:
        open_recording(self.book, self.registry, recording_id, shift_id, 'K', revision_id)
        for sequence, raw in enumerate(codes, start=1):
            append(self.book, recording_id, sequence, raw)
        return seal(self.book, self.originals, recording_id)

    def archive(self, recording_id):
        return archive(self.source, self.reports, recording_id)

    def holds_original(self, recording_id: str) -> bool:
        try:
            self.originals.get(recording_id)
        except KeyError:
            return False
        return True

    def reject_receipt_writes(self) -> None:
        self.connection.execute('''
            CREATE TEMP TRIGGER fail_fixture_receipt BEFORE INSERT ON receipts
            WHEN EXISTS (SELECT 1 FROM reports WHERE report_key = NEW.report_key)
            BEGIN
                SELECT RAISE(ABORT, 'fixture receipt write failed');
            END
        ''')

    def reject_next_commit(self) -> None:
        armed = True

        def authorize(action, argument, unused, database, origin):
            nonlocal armed
            if armed and action == sqlite3.SQLITE_TRANSACTION and argument == 'COMMIT':
                armed = False
                self.denied_commits += 1
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.connection.set_authorizer(authorize)

    def counts(self) -> tuple[int, int, int, int, int]:
        row = self.connection.execute('''
            SELECT (SELECT COUNT(*) FROM reports), (SELECT COUNT(*) FROM receipts),
                   (SELECT COUNT(*) FROM discards), (SELECT COUNT(*) FROM handovers),
                   (SELECT COUNT(*) FROM handover_reports)
        ''').fetchone()
        return tuple(row)
