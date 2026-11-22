from archive.reports import ReportStore
from archive.storage import station_transaction
from maintenance.eligible import require_discardable
from maintenance.history import DiscardFact, DiscardHistory
from maintenance.session import require_maintenance
from record.mode import DeviceState
from record.rulings import rulings_of
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
    book = rulings_of(device)
    with station_transaction(history.connection):
        require_discardable(device.device_id, originals, reports, recording_id)
        # A recording already qualified for archiving cannot be voided, even
        # while the station receipt is still outstanding.
        if book.blocks_maintenance_discard(recording_id):
            raise ValueError(f'recording {recording_id!r} is qualified for archiving')
        # The first successful discard reason is authoritative: a later
        # maintenance entry that disagrees with a live discard is refused.
        existing_reason = book.reason(recording_id)
        if existing_reason is not None and existing_reason != reason:
            raise ValueError(f'conflicting discard reason for {recording_id!r}')
        fact = history.remember(DiscardFact(device.device_id, recording_id, reason))
        # Mirror the maintenance verdict into the device book (keeping the
        # authoritative reason) so resumed recording, live ports and later
        # maintenance calls all obey the same decision.
        book.discard(recording_id, fact.reason)
        book.get(recording_id).reason = fact.reason
        return fact
