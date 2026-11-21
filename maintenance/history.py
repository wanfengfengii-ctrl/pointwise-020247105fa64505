import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiscardFact:
    device_id: str
    recording_id: str
    reason: str


def initialize_discard_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS discards (
            device_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY (device_id, recording_id)
        )
    ''')


class DiscardHistory:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def find(self, device_id: str, recording_id: str) -> DiscardFact | None:
        row = self.connection.execute(
            'SELECT reason FROM discards WHERE device_id = ? AND recording_id = ?',
            (device_id, recording_id),
        ).fetchone()
        if row is None:
            return None
        return DiscardFact(device_id, recording_id, row['reason'])

    def remember(self, fact: DiscardFact) -> DiscardFact:
        cursor = self.connection.execute('''
            INSERT INTO discards (device_id, recording_id, reason) VALUES (?, ?, ?)
            ON CONFLICT (device_id, recording_id) DO NOTHING
        ''', (fact.device_id, fact.recording_id, fact.reason))
        if cursor.rowcount == 1:
            return fact
        existing = self.find(fact.device_id, fact.recording_id)
        if existing is None or existing.reason != fact.reason:
            raise ValueError(f'conflicting discard reason for {fact.recording_id!r}')
        return existing
