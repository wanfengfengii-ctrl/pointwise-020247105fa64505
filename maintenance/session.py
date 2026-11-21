from record.mode import DeviceMode, DeviceState


def maintenance(device: DeviceState, entering: bool) -> DeviceMode:
    if type(entering) is not bool:
        raise ValueError('maintenance request must specify entering or exiting')
    if entering:
        device.enter_maintenance()
    else:
        device.exit_maintenance()
    return device.mode


def require_maintenance(device: DeviceState) -> None:
    if device.mode is not DeviceMode.MAINTENANCE:
        raise RuntimeError('discard requires maintenance mode')
