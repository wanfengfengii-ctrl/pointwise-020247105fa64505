# 澄湾港区台架振动试验站

值班员从本地记录器收取有序整数原码。停机后，站库签发可复算的振动速度报告。现场人员在维护态处理夹具松脱等废测，质检员用已签报告交班。后班可在设备停源后追溯峰值所在测点和完整波形。

## 运行

需要 Python 3.11 和其标准库。命令在项目根目录执行。控制台物化项目时提供 `check_project.py`。

```sh
python3 -B check_project.py
python3 -B -m demo --input samples/day.json
```

也可直接使用 unittest 发现完整测试。

```sh
python3 -B -m unittest discover -s tests -t . -p 'test_*.py'
```

`python3 -B check_project.py` 除完整 unittest 回归外，还运行 `live_fixture` 的设备/站库联合核验（停机路径与不停采路径），任一失败返回非零。`python3 -B -m live_demo` 运行实际作废与实收链路并展示停源领取。

演示创建独立的临时站库，停源后重开并输出实际 JSON。失败时向标准错误报告原因，退出码为 1。参数用法错误由 argparse 返回 2。

## 早班样例

1. 登记 K/J1，每码 1 mm/s，阈值 10 mm/s。
2. 开测 A 并冻结 J1，再登记每码 2 mm/s 的 J2。
3. 按源序录入 A 的 −7、11。
4. 封定 A，以 J2 录制 B 的 −5、5，以 J1 录制 C 的 3。封定所有测次后停机。
5. 归档 A 和 B。A 的绝对峰值为 11 mm/s，首次在序 2。B 的绝对峰值为 10 mm/s，首次在序 1。
6. 按两份已签报告签发早班交班单，超限数为 1。
7. 在维护态以夹具松脱为由作废 C。退出维护后 C 的停机送交被拒绝。关闭设备并重开站库，按交班号和各首执复领。

## Python 接口

- `rules.register.register(registry, rule_id, revision_id, scale, threshold)` 接受整数、`Fraction` 和精确有理文本。同号等值重投返回原修订。同号异参、非正系数、负阈值、布尔值和浮点输入拒绝。
- 创建 `DeviceState(device_id)`、绑定该设备的 `RunBook(device)` 和 `SealedStore()`。`record.runs.open(book, registry, recording_id, shift_id, rule_id, revision_id)` 开测，`append(book, recording_id, sequence, raw)` 录入，`record.seal.seal(book, originals, recording_id)` 封定。序位正好是已收点数加一，原码为整数。序位错误和空封可在原测次上纠正。`record.mode.stop(device)` 仅在没有活动录制时停机。
- `archive.storage.open_station(path)` 打开并初始化站库，退出上下文时关闭。用连接构造 `ReportStore`、`DiscardHistory` 和 `HandoverNoteStore`。`initialize_station(connection)` 可重复执行，保留正常业务登记的数据。`RecordingSource(device, originals, history.find)` 绑定此站库的废测查询，重开后用新连接装配。
- `archive.intake.archive(source, reports, recording_id)` 仅在停机时受理。成功返回带 `report` 和 `receipt_id` 的结果，重投可复领。归档事务失败抛出 `ArchiveWriteError`，报告和首执均回滚。设备会话仍在线，原件可重读。
- `maintenance.session.maintenance(device, entering)` 进入或退出维护。`maintenance.discard.discard(device, originals, history, recording_id, reason)` 核对已封和未签，登记具名原因。同原因返回原事实。`history.find(device_id, recording_id)` 可追溯原因。
- `handover.issue.issue(reports, notes, shift_id, report_ids)` 签发交班单。它校验全部引用并按报告号固定顺序，以签发时的判级统计超限。空交班单的超限数为零。`handover.lookup.lookup(reports, notes, reference)` 根据首执返回归档结果，或根据交班号返回固定交班单。`reports.get_report(report_id)` 读取交班单引用的已签报告。停机后可用 `device.power_off()` 停源，历史查询使用站库连接。

## 不停采裁决接口（LIVE.md）

需要不停采作废的会话在开测前用 `live=True` 装配供件端口：`RecordingSource(device, originals, history.find, live=True)`。裁决信息保存在设备侧的 `record.rulings.RulingBook`（经 `rulings_of(device)` 取用），不查询活动的 SQLite 连接，站库关闭时同样可裁定；重开站库后用同一 `device`、`originals` 和新连接重新装配端口，已有裁决与确认继续有效。

- `source.discard_live(recording_id, reason)` 仅在运行态受理已封测次，返回 `'discarded'` 或 `'claimed'`。首个成功作废的原因保持有效，重投复用设备结果，正在采的另一测次继续接纳原码。
- `source.claim_archive(recording_id)` 在运行或停机态为已封测次请求独占归档资格。已作废返回 `None`，获准返回绑定设备号、测次号、班次、冻结规程和按原序原码的 `ArchiveClaim`，其 `matches(original)` 校验完整封件。已实收释放原件后同号仍可取得并核验原资格。
- `source.confirm_archive(claim)` 接收站库实收确认，只确认本设备授出的相同资格，错绑抛 `ValueError`，未知身份抛 `KeyError`，可重投；确认后 `originals.get(recording_id)` 抛 `KeyError`。
- `archive.intake.archive_live(source, reports, recording_id)` 在运行或停机态受理，返回 `('discarded', None)`、`('retry', None)` 或 `('signed', ArchiveResult)`。资格或原件错配抛 `ValueError` 且无新增成果；端口 `OSError` 与 SQLite 提交失败均为待重试；原码、出处、冻结规程、峰值、判级和首执同次提交后才向设备确认。已提交而确认失答时，重开重投复用同一首执，并用持久原件核对资格补交，不再向设备索取已释放波形。
- 维护入口仍只在维护态受理：已获准归档（含待实收）的测次拒绝维护作废；维护先登记的废测镜像进设备裁决，恢复录制后继续阻止现场和归档绕过；现场先作废时维护入口同原因重投、异原因拒绝。原 `archive` 仍要求停机并遵守该会话的设备裁决。

## 数据与失败语义

标识及原因使用有可见内容的字符串。本站以设备号和测次号共同标识一次物理测次。调用方为物理测次分配不会在同设备号下重复的测次号。规程、活动缓冲和设备封件服务于当前设备会话。废测事实、报告、首执和交班单保存在本站 SQLite。一次停机处置完成后再开启下一动作。

原件保留设备、班次、测次、冻结规程和连续原序。归档用每点原码乘冻结系数求带符号速度，取绝对值最大的首次源序，严格大于冻结阈值才算超限。所有数值按精确有理数处理。查询还原完整原码及精确量值，后班可以独立复算。

未知身份或凭据抛出 `KeyError`。非法输入、原件错配和业务冲突抛出 `ValueError`。设备模式错误抛出 `RuntimeError`。废测供件抛出 `DiscardedOriginal`，属于 `ValueError`。关机后设备拒绝供件。完整回归覆盖拒绝后的续录、归档回滚和重投、已签测次防误作废以及断源复领。
