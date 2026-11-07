from __future__ import annotations

from collections.abc import Iterable

# 按优先级排列：同一个字典里 mph 比 rmid 更可能是可用表号。
# 实测 queryAccountInfo 会同时返回 mph 与 rmid，两者值不同，
# 其中只有 mph 能通过 queryDayData / valveStatus 的权限校验。
METER_KEYS = (
    "mph",
    "meterno",
    "meter_no",
    "mtrno",
    "mtr_no",
    "gasmeterno",
    "rawmeterno",
    "deviceno",
    "meternum",
    "meternumber",
    "metersn",
    "rmid",
    "deviceid",
    "gasmeterid",
    "meterid",
    "meter_id",
)


def iter_meter_values(value) -> Iterable[str]:
    """Yield likely meter numbers from nested API data."""
    if isinstance(value, dict):
        normalized = {str(key).lower(): item for key, item in value.items()}
        for key in METER_KEYS:
            item = normalized.get(key)
            if item in (None, ""):
                continue

            text = str(item).strip()
            if text:
                yield text

        for item in value.values():
            yield from iter_meter_values(item)

    elif isinstance(value, list):
        for item in value:
            yield from iter_meter_values(item)
