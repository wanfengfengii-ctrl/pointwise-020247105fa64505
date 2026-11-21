from archive.reports import ReportStore
from archive.storage import station_transaction
from maintenance.eligible import require_discardable
from maintenance.history import DiscardFact, DiscardHistory
from maintenance.session import require_maintenance
from record.mode import DeviceState
from record.seal import SealedStore
from rules.validate import require_label


def discard(
    device: DeviceState,
    originals: SealedStore,
    history: DiscardHistory,
    recording_id: str,
    reason: str,
) -> DiscardFact:
    require_maintenance(device)
    require_label(reason, 'discard reason')
    reports = ReportStore(history.connection)
    with station_transaction(history.connection):
        require_discardable(device.device_id, originals, reports, recording_id)
        return history.remember(DiscardFact(device.device_id, recording_id, reason))
