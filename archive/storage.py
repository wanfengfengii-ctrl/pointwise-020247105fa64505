from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3


def open_archive_store(database: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def station_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def initialize_archive_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_key INTEGER PRIMARY KEY,
            device_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            shift_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            scale_num TEXT NOT NULL,
            scale_den TEXT NOT NULL,
            threshold_num TEXT NOT NULL,
            threshold_den TEXT NOT NULL,
            waveform TEXT NOT NULL,
            peak_num TEXT NOT NULL,
            peak_den TEXT NOT NULL,
            peak_sequence INTEGER NOT NULL CHECK (peak_sequence > 0),
            exceeded INTEGER NOT NULL CHECK (exceeded IN (0, 1)),
            UNIQUE (device_id, recording_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            report_key INTEGER PRIMARY KEY REFERENCES reports(report_key)
        )
    ''')


def initialize_station(connection: sqlite3.Connection) -> None:
    from handover.notes import initialize_handover_schema
    from maintenance.history import initialize_discard_schema

    with station_transaction(connection):
        initialize_archive_schema(connection)
        initialize_discard_schema(connection)
        initialize_handover_schema(connection)


@contextmanager
def open_station(database: str | Path) -> Iterator[sqlite3.Connection]:
    connection = open_archive_store(database)
    try:
        initialize_station(connection)
        yield connection
    finally:
        connection.close()


def reference_for(prefix: str, key: int) -> str:
    return f'{prefix}-{key:019d}'


def reference_key(reference: str, prefix: str) -> int:
    start = f'{prefix}-'
    if not isinstance(reference, str) or not reference.startswith(start):
        raise KeyError(reference)
    digits = reference[len(start):]
    if len(digits) != 19 or not digits.isascii() or not digits.isdecimal():
        raise KeyError(reference)
    key = int(digits)
    if not 0 < key <= 2**63 - 1:
        raise KeyError(reference)
    return key
