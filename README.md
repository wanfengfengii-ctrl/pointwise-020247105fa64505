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

## 数据与失败语义

标识及原因使用有可见内容的字符串。本站以设备号和测次号共同标识一次物理测次。调用方为物理测次分配不会在同设备号下重复的测次号。规程、活动缓冲和设备封件服务于当前设备会话。废测事实、报告、首执和交班单保存在本站 SQLite。一次停机处置完成后再开启下一动作。

原件保留设备、班次、测次、冻结规程和连续原序。归档用每点原码乘冻结系数求带符号速度，取绝对值最大的首次源序，严格大于冻结阈值才算超限。所有数值按精确有理数处理。查询还原完整原码及精确量值，后班可以独立复算。

未知身份或凭据抛出 `KeyError`。非法输入、原件错配和业务冲突抛出 `ValueError`。设备模式错误抛出 `RuntimeError`。废测供件抛出 `DiscardedOriginal`，属于 `ValueError`。关机后设备拒绝供件。完整回归覆盖拒绝后的续录、归档回滚和重投、已签测次防误作废以及断源复领。
