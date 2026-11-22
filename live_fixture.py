"""Schedule device calls without deciding their outcomes."""
import json
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path

from archive.commit import ArchiveWriteError
from archive.intake import archive, archive_live
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
        if name not in (
            "read_original",
            "claim_archive",
            "confirm_archive",
            "discard_live",
        ):
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


def check_live_fixture():
    """Exercise both verdicts, a real commit denial and receipt continuation."""
    device = DeviceState("bench-5")
    book = RunBook(device)
    originals = SealedStore()
    registry = RevisionRegistry()
    register(registry, "K", "J1", 1, 10)
    # R is sealed while S keeps capturing; the discard verdict must win.
    open_recording(book, registry, "R", "early", "K", "J1")
    append(book, "R", 1, -7)
    append(book, "R", 2, 11)
    seal(book, originals, "R")
    open_recording(book, registry, "S", "early", "K", "J1")
    append(book, "S", 1, 4)

    with TemporaryDirectory(prefix="chengwan-live-") as directory:
        database = Path(directory) / "station.sqlite3"
        with open_station(database) as connection:
            history = DiscardHistory(connection)
            reports = ReportStore(connection)
            port = fixture_port(device, originals, history.find, live=True)

            # Verdict one: discard wins on the device, no station artefacts.
            assert port.discard_live("R", "夹具松脱") == "discarded"
            assert port.discard_live("R", "电缆折损") == "discarded"
            assert archive_live(port, reports, "R") == ("discarded", None)
            assert reports.find_by_recording("bench-5", "R") is None
            # Capturing the next test never stopped.
            append(book, "S", 2, -9)
            seal(book, originals, "S")

            # Verdict two: archive qualification wins over a later discard.
            claim = port.claim_archive("S")
            assert claim is not None and claim.matches(originals.get("S"))
            assert port.discard_live("S", "夹具松脱") == "claimed"
            assert originals.get("S") is not None

            # The first station commit is genuinely denied at transaction level.
            denied = {"count": 0}

            def authorize(action, argument, unused, database, origin):
                if action == sqlite3.SQLITE_TRANSACTION and argument == "COMMIT":
                    denied["count"] += 1
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            assert archive_live(port, reports, "S") == ("retry", None)
            assert denied["count"] == 1
            rows = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM reports), (SELECT COUNT(*) FROM receipts)"
            ).fetchone())
            assert rows == (0, 0)
            assert originals.get("S") is not None
            connection.set_authorizer(None)

        # Reopen the station and continue from the original adjudication.
        with open_station(database) as connection:
            history = DiscardHistory(connection)
            reports = ReportStore(connection)
            port = fixture_port(device, originals, history.find, live=True)
            status, signed = archive_live(port, reports, "S")
            assert status == "signed"
            assert signed.report.peak.magnitude == 9
            assert signed.report.peak.sequence == 2
            assert signed.report.peak.exceeded is False
            # The device released only the acknowledged waveform.
            try:
                originals.get("S")
            except KeyError:
                released = True
            else:
                released = False
            assert released
            # R was never signed and stays a device-side discard.
            assert reports.find_by_recording("bench-5", "R") is None
            # Replay returns the same single signed result.
            assert archive_live(port, reports, "S") == ("signed", signed)
            recalled = reports.get_by_receipt(signed.receipt_id)
            stop(device)
            device.power_off()
            return {
                "discarded_recording": "R",
                "discarded_rows": 0,
                "signed_recording": "S",
                "waveform": [[s.sequence, s.raw] for s in recalled.report.original.samples],
                "peak": str(recalled.report.peak.magnitude),
                "peak_sequence": recalled.report.peak.sequence,
                "receipt": signed.receipt_id,
                "device_released": released,
            }


def main():
    legacy = check_fixture()
    live = check_live_fixture()
    print(json.dumps({"stopped_path": legacy, "live_path": live},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
