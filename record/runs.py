from dataclasses import dataclass

from record.mode import DeviceState
from record.samples import Sample, SampleBuffer
from rules.freeze import FrozenRule, freeze_revision
from rules.revisions import RevisionRegistry
from rules.validate import require_label


@dataclass(frozen=True, slots=True)
class Recording:
    device_id: str
    recording_id: str
    shift_id: str
    rule: FrozenRule
    samples: SampleBuffer


class RunBook:
    def __init__(self, device: DeviceState) -> None:
        self.device = device
        self._used: set[str] = set()
        self._active: Recording | None = None

    def get_active(self, recording_id: str) -> Recording:
        require_label(recording_id, 'recording id')
        if recording_id not in self._used:
            raise KeyError(recording_id)
        current = self._active
        if current is None or current.recording_id != recording_id:
            raise ValueError(f'recording {recording_id!r} is not active')
        return current

    def finish(self, recording_id: str) -> None:
        self.get_active(recording_id)
        self.device.finish_recording(recording_id)
        self._active = None


def open(
    book: RunBook,
    registry: RevisionRegistry,
    recording_id: str,
    shift_id: str,
    rule_id: str,
    revision_id: str,
) -> Recording:
    require_label(recording_id, 'recording id')
    require_label(shift_id, 'shift id')
    if recording_id in book._used:
        raise ValueError(f'recording {recording_id!r} has already been used')
    rule = freeze_revision(registry.get(rule_id, revision_id))
    recording = Recording(book.device.device_id, recording_id, shift_id, rule, SampleBuffer())
    book.device.begin_recording(recording_id)
    book._active = recording
    book._used.add(recording_id)
    return recording


def append(book: RunBook, recording_id: str, sequence: int, raw: int) -> Sample:
    return book.get_active(recording_id).samples.append(sequence, raw)
