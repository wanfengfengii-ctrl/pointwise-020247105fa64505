from dataclasses import dataclass
import sqlite3

from archive.storage import reference_for, reference_key, station_transaction
from handover.summary import ShiftSummary


@dataclass(frozen=True, slots=True)
class HandoverNote:
    handover_id: str
    shift_id: str
    report_ids: tuple[str, ...]
    exceeded_count: int


def initialize_handover_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS handovers (
            handover_key INTEGER PRIMARY KEY,
            shift_id TEXT NOT NULL,
            exceeded_count INTEGER NOT NULL CHECK (exceeded_count >= 0)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS handover_reports (
            handover_key INTEGER NOT NULL REFERENCES handovers(handover_key),
            position INTEGER NOT NULL,
            report_key INTEGER NOT NULL REFERENCES receipts(report_key),
            PRIMARY KEY (handover_key, position),
            UNIQUE (handover_key, report_key)
        )
    ''')


class HandoverNoteStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, summary: ShiftSummary) -> HandoverNote:
        report_keys = [reference_key(report_id, 'report') for report_id in summary.report_ids]
        with station_transaction(self.connection):
            cursor = self.connection.execute('''
                INSERT INTO handovers (shift_id, exceeded_count) VALUES (?, ?)
            ''', (summary.shift_id, summary.exceeded_count))
            key = cursor.lastrowid
            self.connection.executemany('''
                INSERT INTO handover_reports (handover_key, position, report_key) VALUES (?, ?, ?)
            ''', ((key, position, report_key) for position, report_key in enumerate(report_keys, 1)))
        return HandoverNote(
            reference_for('handover', key), summary.shift_id, summary.report_ids,
            summary.exceeded_count,
        )

    def get(self, handover_id: str) -> HandoverNote:
        key = reference_key(handover_id, 'handover')
        note = self.connection.execute('''
            SELECT shift_id, exceeded_count FROM handovers WHERE handover_key = ?
        ''', (key,)).fetchone()
        if note is None:
            raise KeyError(handover_id)
        rows = self.connection.execute('''
            SELECT report_key FROM handover_reports WHERE handover_key = ? ORDER BY position
        ''', (key,))
        references = tuple(reference_for('report', row['report_key']) for row in rows)
        return HandoverNote(handover_id, note['shift_id'], references, note['exceeded_count'])
