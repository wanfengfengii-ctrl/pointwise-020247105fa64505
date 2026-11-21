from enum import Enum

from rules.validate import require_label


class DeviceMode(str, Enum):
    STOPPED = 'stopped'
    RUNNING = 'running'
    MAINTENANCE = 'maintenance'
    OFFLINE = 'offline'


class DeviceState:
    def __init__(self, device_id: str) -> None:
        self._device_id = require_label(device_id, 'device id')
        self._mode = DeviceMode.STOPPED
        self._active: str | None = None

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def mode(self) -> DeviceMode:
        return self._mode

    @property
    def active_recording(self) -> str | None:
        return self._active

    def begin_recording(self, recording_id: str) -> None:
        if self._mode not in (DeviceMode.STOPPED, DeviceMode.RUNNING):
            raise RuntimeError('device cannot record in its current mode')
        if self._active is not None:
            raise RuntimeError('device already has an active recording')
        self._active = recording_id
        self._mode = DeviceMode.RUNNING

    def finish_recording(self, recording_id: str) -> None:
        if self._mode is not DeviceMode.RUNNING or self._active != recording_id:
            raise RuntimeError('recording does not own the active slot')
        self._active = None

    def enter_maintenance(self) -> None:
        if self._mode is not DeviceMode.STOPPED:
            raise RuntimeError('maintenance requires a stopped device')
        self._mode = DeviceMode.MAINTENANCE

    def exit_maintenance(self) -> None:
        if self._mode is not DeviceMode.MAINTENANCE:
            raise RuntimeError('device is not in maintenance')
        self._mode = DeviceMode.STOPPED

    def power_off(self) -> None:
        if self._mode is not DeviceMode.STOPPED:
            raise RuntimeError('power off requires a stopped device')
        self._mode = DeviceMode.OFFLINE


def stop(device: DeviceState) -> None:
    if device.mode not in (DeviceMode.RUNNING, DeviceMode.STOPPED):
        raise RuntimeError('device cannot stop in its current mode')
    if device.active_recording is not None:
        raise RuntimeError('seal the active recording before stopping')
    device._mode = DeviceMode.STOPPED
