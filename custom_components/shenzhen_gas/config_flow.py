from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ShenzhenGasApi,
    ShenzhenGasApiError,
    ShenzhenGasChannelError,
    ShenzhenGasPermissionError,
)
from .const import (
    CONF_CCB_CUST_NO,
    CONF_CODE_ID,
    CONF_METER_NO,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_UPDATE_INTERVAL_MINUTES,
    MIN_UPDATE_INTERVAL_MINUTES,
    entry_data_without_legacy,
)
from .meter import iter_meter_values

_LOGGER = logging.getLogger(__name__)


def _clean(value: str) -> str:
    """Normalize a user supplied value (复制粘贴常带引号/空格)。"""
    return (value or "").strip().strip('"').strip("'").strip()


class ShenzhenGasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Shenzhen Gas.

    用户只需填一个 CodeId：客户号、表号、accountChannelId 全部由接口自动识别。
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._accounts: list[dict] = []
        self._selected_account: dict | None = None
        self._code_id: str | None = None

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            self._code_id = _clean(user_input[CONF_CODE_ID])

            if not self._code_id:
                errors["base"] = "invalid_code_id"
            else:
                try:
                    self._accounts = await self._async_get_bound_accounts()
                except ShenzhenGasPermissionError as err:
                    _LOGGER.warning("CodeId 被服务端拒绝访问: %s", err)
                    errors["base"] = "code_id_rejected"
                except ShenzhenGasChannelError as err:
                    _LOGGER.warning("CodeId 无法解析账号: %s", err)
                    errors["base"] = "invalid_code_id"
                except ShenzhenGasApiError as err:
                    _LOGGER.exception("读取绑定账户失败: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if len(self._accounts) == 1:
                        self._selected_account = self._accounts[0]
                        try:
                            return await self._async_create_entry_from_selected_account()
                        except ShenzhenGasApiError as err:
                            _LOGGER.exception("创建配置项失败: %s", err)
                            errors["base"] = "cannot_connect"

                    elif self._accounts:
                        return await self.async_step_account()

                    else:
                        errors["base"] = "no_accounts"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_CODE_ID): str}),
            errors=errors,
        )

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(config_entry=None):
        """Return the options flow used to update CodeId later.

        参数 ``config_entry`` 是 HA 2024.8~2025.6 的调用签名，保留成可选参数
        以兼容后续版本不再传参的改动；OptionsFlow 自己会拿到 config_entry
        （新版有 ``config_entry`` 属性，旧版靠 ``handler``），所以不往里传。
        """
        return ShenzhenGasOptionsFlow()

    async def async_step_account(self, user_input=None):
        """Handle account selection when multiple bound accounts exist."""
        errors = {}

        if user_input is not None:
            try:
                self._selected_account = self._accounts[int(user_input["account"])]
                return await self._async_create_entry_from_selected_account()
            except (IndexError, ValueError, ShenzhenGasApiError) as err:
                _LOGGER.exception("选择账户失败: %s", err)
                errors["base"] = "cannot_connect"

        account_options = {
            str(index): self._account_label(account)
            for index, account in enumerate(self._accounts)
        }

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema({vol.Required("account"): vol.In(account_options)}),
            errors=errors,
        )

    def _build_api(
        self,
        *,
        ccb_cust_no: str = "",
        meter_no: str = "",
    ) -> ShenzhenGasApi:
        """Return an API client bound to the current flow input.

        accountChannelId 一律在请求时由 CodeId 自动解析，这里不传。
        """
        return ShenzhenGasApi(
            async_get_clientsession(self.hass),
            ccb_cust_no=ccb_cust_no,
            meter_no=meter_no,
            code_id=self._code_id or "",
        )

    async def _async_get_bound_accounts(self) -> list[dict]:
        """Return accounts bound to the supplied CodeId."""
        return await self._build_api().async_get_bound_accounts()

    async def _async_create_entry_from_selected_account(self):
        """Create entry from the selected bound account."""
        ccb_cust_no = (self._selected_account or {}).get("ccbCustNo")
        meter_no = await self._async_guess_meter_no(
            self._selected_account or {},
            ccb_cust_no,
        )

        return await self._async_create_entry_from_account(
            self._selected_account or {},
            meter_no,
        )

    async def _async_create_entry_from_account(
        self,
        account: dict,
        meter_no: str,
    ):
        """Create a config entry from a bound account."""
        ccb_cust_no = account.get("ccbCustNo")
        if not ccb_cust_no:
            raise ShenzhenGasApiError("Bound account has no ccbCustNo")

        await self.async_set_unique_id(f"{ccb_cust_no}_{meter_no}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"深圳燃气 {meter_no}",
            data={
                CONF_CCB_CUST_NO: ccb_cust_no,
                CONF_METER_NO: meter_no,
                CONF_CODE_ID: self._code_id,
            },
        )

    async def _async_guess_meter_no(
        self,
        account: dict,
        ccb_cust_no: str | None,
    ) -> str:
        """Return the best available meter number candidate."""
        if not ccb_cust_no:
            raise ShenzhenGasApiError("Bound account has no ccbCustNo")

        candidates = await self._async_get_meter_candidates(ccb_cust_no)
        candidates.extend(
            [
                account.get("premId"),
                account.get("extAcctId"),
            ]
        )

        candidate = next((value for value in dict.fromkeys(candidates) if value), None)
        if candidate:
            return str(candidate)

        raise ShenzhenGasApiError("No meter number candidate found")

    async def _async_get_meter_candidates(self, ccb_cust_no: str) -> list[str]:
        """Return possible meter numbers from customer-level IoT meter data."""
        api = self._build_api(ccb_cust_no=ccb_cust_no)

        candidates = []
        try:
            candidates.extend(iter_meter_values(await api.async_get_account_info()))
        except ShenzhenGasApiError:
            pass

        try:
            candidates.extend(iter_meter_values(await api.async_get_balance()))
        except ShenzhenGasApiError:
            pass

        return candidates

    @staticmethod
    def _account_label(account: dict) -> str:
        """Return a human-readable label for a bound account."""
        parts = [
            account.get("address"),
            account.get("ccbCustNo"),
            account.get("premId"),
        ]

        return " / ".join(str(part) for part in parts if part) or "未命名账户"


class ShenzhenGasOptionsFlow(config_entries.OptionsFlow):
    """更新 CodeId / 轮询间隔，不用删掉集成重加。

    CodeId 可能因为换微信号、重新绑定、后端调整而失效，这里让用户直接在
    Home Assistant 网页上改，改完立即重新校验并写回配置项。
    accountChannelId 由 CodeId 自动解析，所以不提供输入项。
    """

    async def async_step_init(self, user_input=None):
        errors = {}
        entry = self._entry()

        if user_input is not None:
            code_id = _clean(user_input[CONF_CODE_ID])
            interval = _parse_interval(
                user_input.get(CONF_UPDATE_INTERVAL_MINUTES), errors
            )

            if not code_id:
                errors["base"] = "invalid_code_id"

            if not errors:
                # 不沿用旧 accountChannelId：CodeId 变了旧渠道号必然失效，
                # 一律按新 CodeId 重新解析。
                api = ShenzhenGasApi(
                    async_get_clientsession(self.hass),
                    ccb_cust_no=entry.data.get(CONF_CCB_CUST_NO, ""),
                    meter_no=entry.data.get(CONF_METER_NO, ""),
                    code_id=code_id,
                )

                try:
                    await api.async_resolve_account_channel_id()
                    await api.async_get_bound_accounts()
                except ShenzhenGasPermissionError as err:
                    _LOGGER.warning("CodeId 被服务端拒绝访问: %s", err)
                    errors["base"] = "code_id_rejected"
                except ShenzhenGasChannelError as err:
                    _LOGGER.warning("CodeId 无法解析账号: %s", err)
                    errors["base"] = "invalid_code_id"
                except ShenzhenGasApiError as err:
                    _LOGGER.exception("校验 CodeId 失败: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    # data 或 options 任一变化，HA 都会触发 update listener
                    # （见 __init__.py 注册的 reload），不需要手动重载。
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data=entry_data_without_legacy(entry.data, code_id),
                    )

                    return self.async_create_entry(
                        title="",
                        data={CONF_UPDATE_INTERVAL_MINUTES: interval},
                    )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CODE_ID, default=entry.data.get(CONF_CODE_ID, "")
                    ): str,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL_MINUTES,
                        default=entry.options.get(
                            CONF_UPDATE_INTERVAL_MINUTES,
                            DEFAULT_UPDATE_INTERVAL_MINUTES,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_UPDATE_INTERVAL_MINUTES,
                            max=MAX_UPDATE_INTERVAL_MINUTES,
                        ),
                    ),
                }
            ),
            errors=errors,
        )

    def _entry(self):
        """Return the config entry this options flow belongs to.

        兼容不同 HA 版本：新版本有 ``config_entry`` 属性，旧版本用 ``handler``。
        """
        entry = getattr(self, "config_entry", None)
        if entry is not None:
            return entry

        return self.hass.config_entries.async_get_entry(self.handler)


def _parse_interval(value, errors: dict) -> int:
    """Validate the polling interval from user input."""
    if value in (None, ""):
        return DEFAULT_UPDATE_INTERVAL_MINUTES

    try:
        minutes = int(value)
    except (TypeError, ValueError):
        errors["base"] = "invalid_update_interval"
        return DEFAULT_UPDATE_INTERVAL_MINUTES

    if not MIN_UPDATE_INTERVAL_MINUTES <= minutes <= MAX_UPDATE_INTERVAL_MINUTES:
        errors["base"] = "invalid_update_interval"
        return DEFAULT_UPDATE_INTERVAL_MINUTES

    return minutes
