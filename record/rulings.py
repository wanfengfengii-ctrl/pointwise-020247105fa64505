"""Device-side adjudication between live discard and archive claims.

A physical recording gets exactly one verdict on the device.  Maintenance
discards, on-device live discards and exclusive archive qualifications all
flow through :class:`RulingBook`, so replaying any request reuses the original
decision and neither side can overwrite the other.
"""
from dataclasses import dataclass

from record.seal import SealedOriginal
from rules.validate import require_label


@dataclass(frozen=True, slots=True)
class ArchiveClaim:
    """Exclusive archive qualification bound to one sealed waveform."""

    device_id: str
    recording_id: str
    shift_id: str
    rule_id: str
    revision_id: str
    scale_num: int
    scale_den: int
    threshold_num: int
    threshold_den: int
    samples: tuple[tuple[int, int], ...]

    @classmethod
    def for_original(cls, original: SealedOriginal) -> 'ArchiveClaim':
        rule = original.rule
        return cls(
            original.device_id,
            original.recording_id,
            original.shift_id,
            rule.rule_id,
            rule.revision_id,
            rule.scale.numerator,
            rule.scale.denominator,
            rule.threshold.numerator,
            rule.threshold.denominator,
            tuple((sample.sequence, sample.raw) for sample in original.samples),
        )

    def matches(self, original: SealedOriginal) -> bool:
        """Check the claim against a complete sealed waveform."""
        if not hasattr(original, 'samples') or not hasattr(original, 'rule'):
            return False
        samples = tuple((sample.sequence, sample.raw) for sample in original.samples)
        rule = original.rule
        return (
            getattr(original, 'device_id', None) == self.device_id
            and getattr(original, 'recording_id', None) == self.recording_id
            and getattr(original, 'shift_id', None) == self.shift_id
            and getattr(rule, 'rule_id', None) == self.rule_id
            and getattr(rule, 'revision_id', None) == self.revision_id
            and getattr(rule, 'scale', None) is not None
            and (rule.scale.numerator, rule.scale.denominator)
            == (self.scale_num, self.scale_den)
            and (rule.threshold.numerator, rule.threshold.denominator)
            == (self.threshold_num, self.threshold_den)
            and samples == self.samples
        )


@dataclass(slots=True)
class _Ruling:
    state: str  # 'discarded' | 'claimed' | 'released'
    reason: str | None = None
    claim: ArchiveClaim | None = None


class RulingBook:
    """In-device verdicts keyed by recording id.

    The book never touches a SQLite connection, so on-device adjudication
    works while the station database is closed.
    """

    def __init__(self, device_id: str) -> None:
        self._device_id = device_id
        self._rulings: dict[str, _Ruling] = {}

    def _require_known(self, recording_id: str) -> _Ruling:
        require_label(recording_id, 'recording id')
        try:
            return self._rulings[recording_id]
        except KeyError:
            raise KeyError(recording_id) from None

    def get(self, recording_id: str) -> _Ruling:
        return self._require_known(recording_id)

    def state(self, recording_id: str) -> str | None:
        require_label(recording_id, 'recording id')
        ruling = self._rulings.get(recording_id)
        return None if ruling is None else ruling.state

    def reason(self, recording_id: str) -> str | None:
        require_label(recording_id, 'recording id')
        ruling = self._rulings.get(recording_id)
        return None if ruling is None else ruling.reason

    def claim(self, recording_id: str) -> ArchiveClaim | None:
        require_label(recording_id, 'recording id')
        ruling = self._rulings.get(recording_id)
        return None if ruling is None else ruling.claim

    def discard(self, recording_id: str, reason: str) -> str:
        """Adjudicate a discard; returns 'discarded' or 'claimed'."""
        require_label(recording_id, 'recording id')
        require_label(reason, 'discard reason')
        ruling = self._rulings.get(recording_id)
        if ruling is None:
            self._rulings[recording_id] = _Ruling('discarded', reason=reason)
            return 'discarded'
        if ruling.state == 'discarded':
            return 'discarded'
        return 'claimed'

    def grant(self, recording_id: str, claim: ArchiveClaim) -> ArchiveClaim | None:
        """Grant an archive qualification, or report an existing verdict."""
        require_label(recording_id, 'recording id')
        ruling = self._rulings.get(recording_id)
        if ruling is None:
            ruling = _Ruling('claimed', claim=claim)
            self._rulings[recording_id] = ruling
            return claim
        if ruling.state == 'discarded':
            return None
        return ruling.claim

    def confirm(self, recording_id: str, claim: ArchiveClaim) -> None:
        """Record the station's receipt acknowledgement for a claim."""
        ruling = self._require_known(recording_id)
        if ruling.claim is None or ruling.claim != claim:
            raise ValueError('archive confirmation is not bound to this device claim')
        ruling.state = 'released'

    def is_discarded(self, recording_id: str) -> bool:
        require_label(recording_id, 'recording id')
        ruling = self._rulings.get(recording_id)
        return ruling is not None and ruling.state == 'discarded'

    def blocks_maintenance_discard(self, recording_id: str) -> bool:
        require_label(recording_id, 'recording id')
        ruling = self._rulings.get(recording_id)
        return ruling is not None and ruling.state in ('claimed', 'released')


def rulings_of(device) -> RulingBook:
    """Return the verdict book attached to a device, creating it once."""
    book = getattr(device, '_rulings', None)
    if book is None:
        book = RulingBook(device.device_id)
        device._rulings = book
    return book
