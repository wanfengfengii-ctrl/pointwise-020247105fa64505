from collections.abc import Callable

from record.mode import DeviceMode, DeviceState
from record.seal import SealedOriginal, SealedStore


class DiscardedOriginal(ValueError):
    pass


class RecordingSource:
    def __init__(
        self,
        device: DeviceState,
        originals: SealedStore,
        find_discard: Callable[[str, str], object | None],
    ) -> None:
        self._device = device
        self._originals = originals
        self._find_discard = find_discard

    @property
    def device_id(self) -> str:
        return self._device.device_id

    def current_mode(self) -> DeviceMode:
        return self._device.mode

    def read_original(self, recording_id: str) -> SealedOriginal:
        if self.current_mode() is DeviceMode.OFFLINE:
            raise RuntimeError('device is offline')
        original = self._originals.get(recording_id)
        if self._find_discard(self.device_id, recording_id) is not None:
            raise DiscardedOriginal(f'recording {recording_id!r} was discarded')
        return original
