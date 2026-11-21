"""Schedule device calls without deciding their outcomes."""
import json
import sqlite3

from archive.commit import ArchiveWriteError
from archive.intake import archive
from archive.reports import ReportStore
from archive.storage import open_station
from maintenance.history import DiscardHistory
from record.mode import DeviceState, stop
from record.runs import RunBook, append, open as open_recording
from record.seal import SealedStore, seal
from record.source import RecordingSource
from rules.register import register
from rules.revisions import RevisionRegistry


class ScheduledPort:
    def __init__(self, port):
        self.port = port
        self.before = {}
        self.after = {}
        self.calls = []

    def __getattr__(self, name):
        method = getattr(self.port, name)
        if name not in ("read_original", "claim_archive", "confirm_archive"):
            return method

        def call(*args, **kwargs):
            self.calls.append(name)
            before = self.before.pop(name, None)
            if before is not None:
                before(*args, **kwargs)
            result = method(*args, **kwargs)
            after = self.after.pop(name, None)
            if after is None:
                return result
            return after(result)

        return call


def fixture_port(device, originals, find_discard, *, live=False):
    options = {"live": True} if live else {}
    return ScheduledPort(RecordingSource(device, originals, find_discard, **options))


def check_fixture():
    device = DeviceState("bench-4")
    book = RunBook(device)
    originals = SealedStore()
    registry = RevisionRegistry()
    register(registry, "K", "J1", 1, 10)
    open_recording(book, registry, "R", "early", "K", "J1")
    append(book, "R", 1, -7)
    append(book, "R", 2, 11)
    sealed = seal(book, originals, "R")
    open_recording(book, registry, "S", "early", "K", "J1")

    with open_station(":memory:") as connection:
        history = DiscardHistory(connection)
        reports = ReportStore(connection)
        port = fixture_port(device, originals, history.find)
        observed = []

        def before_read(recording_id):
            assert recording_id == "R"
            append(book, "S", 1, 3)

        def after_read(original):
            observed.append(original.recording_id)
            return original

        port.before["read_original"] = before_read
        port.after["read_original"] = after_read
        assert port.read_original("R") is sealed
        assert observed == ["R"]
        assert seal(book, originals, "S").samples[0].raw == 3
        stop(device)
        denied = []

        def authorize(action, argument, unused, database, origin):
            if action == sqlite3.SQLITE_TRANSACTION and argument == "COMMIT" and not denied:
                denied.append(argument)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        try:
            archive(port, reports, "R")
        except ArchiveWriteError:
            assert denied == ["COMMIT"]
        else:
            raise AssertionError("fixture did not deny the station commit")
        rows = tuple(connection.execute(
            "SELECT (SELECT COUNT(*) FROM reports), (SELECT COUNT(*) FROM receipts)"
        ).fetchone())
        assert rows == (0, 0)
        assert originals.get("R") is sealed
        signed = archive(port, reports, "R")
        assert signed.report.peak.magnitude == 11
        assert reports.get_by_receipt(signed.receipt_id) == signed
        return {"read": observed, "rolled_back_rows": rows,
                "continued_samples": len(originals.get("S").samples),
                "peak": str(signed.report.peak.magnitude), "receipt": signed.receipt_id}


if __name__ == "__main__":
    print(json.dumps(check_fixture(), sort_keys=True))
