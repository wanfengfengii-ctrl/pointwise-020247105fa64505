from collections.abc import Callable

from record.mode import DeviceMode, DeviceState
from record.rulings import ArchiveClaim, rulings_of
from record.seal import SealedOriginal, SealedStore


class DiscardedOriginal(ValueError):
    pass


class RecordingSource:
    def __init__(
        self,
        device: DeviceState,
        originals: SealedStore,
        find_discard: Callable[[str, str], object | None],
        *,
        live: bool = False,
    ) -> None:
        if type(live) is not bool:
            raise ValueError('live must be a boolean switch')
        self._device = device
        self._originals = originals
        self._find_discard = find_discard
        self._live = live

    @property
    def device_id(self) -> str:
        return self._device.device_id

    @property
    def live(self) -> bool:
        return self._live

    def current_mode(self) -> DeviceMode:
        return self._device.mode

    def _ruling_discarded(self, recording_id: str) -> bool:
        return rulings_of(self._device).is_discarded(recording_id)

    def _station_discarded(self, recording_id: str) -> bool:
        return self._find_discard(self.device_id, recording_id) is not None

    def read_original(self, recording_id: str) -> SealedOriginal:
        if self.current_mode() is DeviceMode.OFFLINE:
            raise RuntimeError('device is offline')
        original = self._originals.get(recording_id)
        if self._ruling_discarded(recording_id) or self._station_discarded(recording_id):
            raise DiscardedOriginal(f'recording {recording_id!r} was discarded')
        return original

    def discard_live(self, recording_id: str, reason: str) -> str:
        """Adjudicate a sealed recording while the bench keeps capturing."""
        if not self._live:
            raise RuntimeError('live discard requires a live source')
        if self.current_mode() is not DeviceMode.RUNNING:
            raise RuntimeError('live discard requires a running device')
        # Unknown or not-yet-sealed recordings are rejected before the verdict.
        self._originals.get(recording_id)
        # The verdict is local to the device; the station connection is never
        # consulted, so adjudication works while the station database is closed.
        return rulings_of(self._device).discard(recording_id, reason)

    def claim_archive(self, recording_id: str) -> ArchiveClaim | None:
        """Request the exclusive archive qualification for a sealed recording."""
        if not self._live:
            raise RuntimeError('archive claims require a live source')
        if self.current_mode() not in (DeviceMode.RUNNING, DeviceMode.STOPPED):
            raise RuntimeError('device cannot grant archive claims in its current mode')
        book = rulings_of(self._device)
        existing = book.claim(recording_id)
        if existing is not None:
            return existing
        if book.state(recording_id) == 'discarded':
            return None
        original = self._originals.get(recording_id)
        return book.grant(recording_id, ArchiveClaim.for_original(original))

    def confirm_archive(self, claim: ArchiveClaim) -> None:
        """Accept the station's receipt acknowledgement and release the waveform."""
        if not self._live:
            raise RuntimeError('archive confirmations require a live source')
        if type(claim) is not ArchiveClaim:
            raise ValueError('confirmation requires an ArchiveClaim')
        if self.current_mode() not in (DeviceMode.RUNNING, DeviceMode.STOPPED):
            raise RuntimeError('device cannot confirm archives in its current mode')
        recording_id = claim.recording_id
        book = rulings_of(self._device)
        # Unknown or never-qualified recordings are identity failures; a claim
        # bound to a different recording is a binding failure.
        ruling = book.get(recording_id)
        if ruling.claim is None or ruling.claim != claim:
            raise ValueError('archive confirmation is not bound to this device claim')
        book.confirm(recording_id, claim)
        self._originals.release(recording_id)
