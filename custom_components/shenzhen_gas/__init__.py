from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShenzhenGasApi
from .const import (
    CONF_CCB_CUST_NO,
    CONF_CODE_ID,
    CONF_METER_NO,
    DOMAIN,
    PLATFORMS,
    entry_data_without_legacy,
    has_legacy_channel_data,
)
from .coordinator import ShenzhenGasCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    # accountChannelId 不落盘、也不需要用户填写：每次启动由 CodeId 自动解析。
    api = ShenzhenGasApi(
        session,
        ccb_cust_no=entry.data[CONF_CCB_CUST_NO],
        meter_no=entry.data[CONF_METER_NO],
        code_id=entry.data[CONF_CODE_ID],
    )

    coordinator = ShenzhenGasCoordinator(hass, api, entry.options)
    await coordinator.async_config_entry_first_refresh()

    # 自动纠正表号，并清掉旧版本遗留的 accountChannelId 字段。
    updates = {}
    if api.meter_no != entry.data[CONF_METER_NO]:
        updates[CONF_METER_NO] = api.meter_no

    if has_legacy_channel_data(entry.data):
        cleaned = entry_data_without_legacy(entry.data, entry.data[CONF_CODE_ID])
        updates = {**cleaned, **updates}

    if updates:
        hass.config_entries.async_update_entry(
            entry,
            title=(
                f"深圳燃气 {api.meter_no}"
                if CONF_METER_NO in updates
                else entry.title
            ),
            data={**entry.data, **updates},
        )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when data or options change (CodeId / 轮询间隔)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
