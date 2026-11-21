from archive.reports import ReportStore
from record.seal import SealedStore


def require_discardable(
    device_id: str,
    originals: SealedStore,
    reports: ReportStore,
    recording_id: str,
) -> None:
    original = originals.get(recording_id)
    if (original.device_id, original.recording_id) != (device_id, recording_id):
        raise ValueError('sealed original identity mismatch')
    if reports.find_by_recording(device_id, recording_id) is not None:
        raise ValueError(f'recording {recording_id!r} already has a signed report')
