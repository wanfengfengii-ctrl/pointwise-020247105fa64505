from dataclasses import dataclass

from record.runs import RunBook
from record.samples import Sample
from rules.freeze import FrozenRule
from rules.validate import require_label


@dataclass(frozen=True, slots=True)
class SealedOriginal:
    device_id: str
    recording_id: str
    shift_id: str
    rule: FrozenRule
    samples: tuple[Sample, ...]


class SealedStore:
    def __init__(self) -> None:
        self._originals: dict[str, SealedOriginal] = {}

    def get(self, recording_id: str) -> SealedOriginal:
        require_label(recording_id, 'recording id')
        return self._originals[recording_id]

    def add(self, original: SealedOriginal) -> None:
        if original.recording_id in self._originals:
            raise ValueError(f'recording {original.recording_id!r} is already sealed')
        self._originals[original.recording_id] = original


def seal(book: RunBook, store: SealedStore, recording_id: str) -> SealedOriginal:
    recording = book.get_active(recording_id)
    samples = recording.samples.snapshot()
    if not samples:
        raise ValueError('cannot seal an empty recording')
    original = SealedOriginal(
        recording.device_id, recording.recording_id, recording.shift_id,
        recording.rule, samples,
    )
    store.add(original)
    book.finish(recording_id)
    return original
