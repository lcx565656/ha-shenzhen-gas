from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import random

import aiohttp
import async_timeout

from .meter import iter_meter_values
from .settings import Settings, get_settings

_LOGGER = logging.getLogger(__name__)


class ShenzhenGasApiError(Exception):
    """Shenzhen Gas API error."""


class ShenzhenGasAuthError(ShenzhenGasApiError):
    """Shenzhen Gas auth error."""


class ShenzhenGasChannelError(ShenzhenGasApiError):
    """CodeId 无法解析出渠道信息（40507）。"""


class ShenzhenGasPermissionError(ShenzhenGasChannelError):
    """CodeId 与 accountChannelId 不匹配，接口拒绝访问（40510）。"""


class ShenzhenGasApi:
    """Client for Shenzhen Gas mini-program API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        ccb_cust_no: str,
        meter_no: str,
        code_id: str,
        account_channel_id: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._ccb_cust_no = ccb_cust_no
        self._meter_no = meter_no
        # 个人敏感信息只在运行时从 HA 配置项传入，不落任何代码/配置文件。
        self._code_id = (code_id or "").strip()
        self._account_channel_id = (account_channel_id or "").strip()
        self._settings = settings or get_settings()

        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def settings(self) -> Settings:
        """Return runtime settings."""
        return self._settings

    @property
    def timeout(self) -> int:
        """Return request timeout in seconds."""
        return self._settings.timeout

    @property
    def meter_no(self) -> str:
        """Return gas meter number."""
        return self._meter_no

    def update_meter_no(self, meter_no: str) -> None:
        """Update gas meter number."""
        self._meter_no = meter_no

    @property
    def ccb_cust_no(self) -> str:
        """Return customer number."""
        return self._ccb_cust_no

    @property
    def code_id(self) -> str:
        """Return CodeId from the mini-program request header."""
        return self._code_id

    @property
    def account_channel_id(self) -> str:
        """Return accountChannelId resolved from CodeId."""
        return self._account_channel_id

    def update_account_channel_id(self, account_channel_id: str | int) -> None:
        """Update accountChannelId."""
        self._account_channel_id = str(account_channel_id).strip()

    @property
    def auth_headers(self) -> dict[str, str]:
        """Return headers for token request."""
        return {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "ChannelTye": self._settings.channel_type,
            "Referer": self._settings.referer,
            "User-Agent": self._settings.user_agent,
        }

    def _build_headers(self, access_token: str) -> dict[str, str]:
        """Return request headers.

        CodeId 是微信小程序的 openid，accountChannelId 是它对应的渠道账号 id。
        深圳燃气的业务接口用这两个值做权限校验：CodeId 决定"你是哪个小程序用户"，
        accountChannelId 决定"你能看哪个账号的数据"。两者不匹配时会返回
        40510 无权限访问。
        """
        headers = {
            "Authorization": f"bearer {access_token}",
            "CodeId": self._code_id,
            "ChannelTye": self._settings.channel_type,
            "HeaderNum": str(random.randint(1, self._settings.header_num_max)),
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Referer": self._settings.referer,
            "User-Agent": self._settings.user_agent,
        }

        if self._account_channel_id:
            headers["accountChannelId"] = self._account_channel_id

        return headers

    async def async_login(self) -> str:
        """Get OAuth access token."""
        url = f"{self._settings.base_url}/api/auth/oauth/token"

        try:
            async with async_timeout.timeout(self.timeout):
                async with self._session.post(
                    url,
                    headers=self.auth_headers,
                    auth=aiohttp.BasicAuth(
                        self._settings.token_client_id,
                        self._settings.token_client_secret,
                    ),
                    data={
                        "grant_type": "client_credentials",
                        "scope": "server",
                    },
                ) as resp:
                    text = await resp.text()

                    if resp.status != 200:
                        raise ShenzhenGasAuthError(
                            f"Auth HTTP {resp.status}: {text[:300]}"
                        )

                    data = await resp.json(content_type=None)

        except ShenzhenGasApiError:
            raise
        except Exception as err:
            raise ShenzhenGasAuthError(f"Auth request failed: {err}") from err

        access_token = data.get("access_token")
        if not access_token:
            raise ShenzhenGasAuthError(f"No access_token in auth response: {data}")

        expires_in = int(data.get("expires_in") or 7200)

        self._access_token = access_token

        # 提前 5 分钟刷新，避免刚好过期
        self._token_expires_at = datetime.now() + timedelta(
            seconds=max(expires_in - 300, 60)
        )

        return access_token

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at
        ):
            return self._access_token

        return await self.async_login()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        retry_auth: bool = True,
    ) -> dict:
        """Send request to Shenzhen Gas API."""
        # 业务接口都要求 accountChannelId 请求头，而它只能由 CodeId 解析得到。
        # 这里统一兜底，调用方不必自己记得先解析一次。
        await self.async_resolve_account_channel_id()

        url = f"{self._settings.base_url}{path}"
        access_token = await self.async_get_access_token()

        try:
            async with async_timeout.timeout(self.timeout):
                async with self._session.request(
                    method,
                    url,
                    headers=self._build_headers(access_token),
                    params=params,
                    json=json,
                ) as resp:
                    text = await resp.text()
                    status = resp.status

        except ShenzhenGasApiError:
            raise
        except Exception as err:
            raise ShenzhenGasApiError(f"Request failed: {err}") from err

        try:
            data = _parse_json(text)
        except Exception:  # noqa: BLE001 - 非 JSON 响应时保留原文
            data = None

        if status in (401, 403) and retry_auth:
            _LOGGER.debug("%s %s 返回 HTTP %s，重新获取 token", method, path, status)
            self._access_token = None
            self._token_expires_at = None
            return await self._request(
                method,
                path,
                params=params,
                json=json,
                retry_auth=False,
            )

        if isinstance(data, dict):
            code = data.get("code")
            msg = str(data.get("msg") or "").strip()

            if code in (401,) or "token失效" in msg:
                if retry_auth:
                    _LOGGER.debug("%s %s token 失效，重新获取 token", method, path)
                    self._access_token = None
                    self._token_expires_at = None
                    return await self._request(
                        method,
                        path,
                        params=params,
                        json=json,
                        retry_auth=False,
                    )
                raise ShenzhenGasAuthError(f"{path} token 失效: {data}")

            if status != 200 or code != 0:
                raise _build_api_error(method, path, status, code, msg, data, text)

            return data.get("data") or {}

        if status != 200:
            raise ShenzhenGasApiError(f"{method} {path} HTTP {status}: {text[:300]}")

        return {}

    async def async_resolve_account_channel_id(self) -> str:
        """Resolve accountChannelId from CodeId.

        微信小程序登录时用 wx.login 拿到 code，换取 openid 并作为 CodeId 发给后端；
        接着调用 /handle/fraccountchannel/findAccountByOpenID 拿到渠道账号 id
        （小程序存在 storage 的 accountId），后续所有业务请求都带这个 id。

        本集成原先写死了一个作者自己的 accountChannelId，导致其他用户必然 40510。
        """
        if self._account_channel_id:
            return self._account_channel_id

        if not self._code_id:
            raise ShenzhenGasChannelError("未填写 CodeId，无法获取 accountChannelId")

        access_token = await self.async_get_access_token()

        try:
            async with async_timeout.timeout(self.timeout):
                async with self._session.get(
                    f"{self._settings.base_url}/api/handle/fraccountchannel/findAccountByOpenID",
                    headers=self._build_headers(access_token),
                    params={
                        "openId": self._code_id,
                        "channelType": self._settings.channel_type,
                        "gzhOpenId": "",
                    },
                ) as resp:
                    text = await resp.text()
                    status = resp.status

        except ShenzhenGasApiError:
            raise
        except Exception as err:
            raise ShenzhenGasChannelError(
                f"解析 accountChannelId 失败: {err}"
            ) from err

        if status != 200:
            raise ShenzhenGasChannelError(
                f"解析 accountChannelId 失败：HTTP {status} {text[:300]}"
            )

        try:
            data = _parse_json(text)
        except Exception as err:  # noqa: BLE001 - 非 JSON 也算解析失败
            raise ShenzhenGasChannelError(
                f"解析 accountChannelId 失败：响应不是 JSON（{err}）"
            ) from err

        if not isinstance(data, dict) or not data.get("id"):
            raise ShenzhenGasChannelError(
                "CodeId 未匹配到任何小程序账号，请确认抓的是深圳燃气小程序"
                f"请求头里的 CodeId（响应: {text[:200]}）"
            )

        self.update_account_channel_id(data["id"])
        _LOGGER.debug("已从 CodeId 解析到 accountChannelId=%s", self._account_channel_id)

        return self._account_channel_id

    async def async_get_bound_accounts(self) -> list[dict]:
        """Get accounts bound to the current mini-program user."""
        account_channel_id = await self.async_resolve_account_channel_id()

        data = await self._request(
            "POST",
            "/api/newcis/frbindingport/receiveBandingAcctIdList",
            json={
                "accountChannelId": account_channel_id,
                "pageNum": 1,
                "pageSize": 100,
                "areaId": "",
                "type": "",
            },
        )

        records = data.get("records", [])
        if not isinstance(records, list):
            return []

        return [record for record in records if isinstance(record, dict)]

    async def async_get_account_info(self) -> dict:
        """Get house/account details for the current customer."""
        return await self._request(
            "GET",
            f"/api/handle/fraccounthouseinfo/queryAccountInfo/{self._ccb_cust_no}",
        )

    async def async_get_day_data(self, year_month: str | None = None) -> dict:
        """Get daily gas usage data for the given month."""
        if year_month is None:
            year_month = datetime.now().strftime("%Y%m")

        return await self._request(
            "GET",
            "/api/handle/network/queryDayData",
            params={
                "ccbCustNo": self._ccb_cust_no,
                "mph": self._meter_no,
                "yearMonth": year_month,
            },
        )

    async def async_get_valve_status(self) -> dict:
        """Get gas meter valve status."""
        return await self._request(
            "GET",
            "/api/handle/network/valveStatus",
            params={
                "ccbCustNo": self._ccb_cust_no,
                "mph": self._meter_no,
            },
        )

    async def async_get_balance(self) -> dict:
        """Get prepaid gas balance and IoT meter data."""
        return await self._request(
            "POST",
            "/api/handle/gasThings/getInternetOfThings",
            json={
                "ccbCustNo": self._ccb_cust_no,
                "isPrePaid": True,
                "xcxMtrFlg": "2",
            },
        )

    async def async_get_bill_data_info(self) -> dict:
        """Get historical bill data."""
        return await self._request(
            "POST",
            "/api/handle/gasBill/getUserBillDataInfo",
            json={
                "acct": self._ccb_cust_no,
            },
        )

    async def async_get_bill_date(self) -> dict:
        """Get homepage bill amount and gas consumption."""
        account_channel_id = await self.async_resolve_account_channel_id()

        return await self._request(
            "GET",
            "/api/newcis/homepage/getBillDate",
            params={"accountChannelId": account_channel_id},
        )

    async def async_get_all(self) -> dict:
        """Get all Shenzhen Gas data."""
        # 渠道解析失败属于致命错误（CodeId 无效 / 未绑定），直接抛出，
        # 让 HA 在界面上报错而不是给出一堆空实体。
        await self.async_resolve_account_channel_id()

        errors: list[ShenzhenGasApiError] = []

        account_info = {}
        try:
            account_info = await self.async_get_account_info()
        except ShenzhenGasApiError as err:
            errors.append(err)

        meter_no = next(iter_meter_values(account_info), None)
        if meter_no and meter_no != self._meter_no:
            self.update_meter_no(meter_no)

        balance = {}
        try:
            balance = await self.async_get_balance()
        except ShenzhenGasApiError as err:
            errors.append(err)

        day_data = {}
        try:
            day_data = await self.async_get_day_data()
        except ShenzhenGasApiError as err:
            errors.append(err)

        valve_status = {}
        try:
            valve_status = await self.async_get_valve_status()
        except ShenzhenGasApiError as err:
            errors.append(err)

        bill_data = {}
        try:
            bill_data = await self.async_get_bill_data_info()
        except ShenzhenGasApiError as err:
            errors.append(err)
            try:
                bill_data = await self.async_get_bill_date()
            except ShenzhenGasApiError as err2:
                errors.append(err2)

        if not any((account_info, balance, day_data, valve_status, bill_data)):
            # 全部接口都失败，多半是 CodeId 失效 / 渠道号变了，抛出去让用户看到。
            raise ShenzhenGasApiError(
                "所有深圳燃气接口都返回失败: " + " | ".join(str(e) for e in errors[:3])
            )

        return {
            "account_info": account_info,
            "day_data": day_data,
            "valve_status": valve_status,
            "balance": balance,
            "bill_data": bill_data,
        }


def _build_api_error(
    method: str,
    path: str,
    status: int,
    code,
    msg: str,
    data: dict,
    text: str,
) -> ShenzhenGasApiError:
    """把深圳燃气的错误码翻译成可操作的中文提示。"""
    detail = f"{method} {path} HTTP {status} code={code} msg={msg or text[:200]}"

    if code == 40507:
        return ShenzhenGasChannelError(
            "CodeId 无法匹配到渠道信息（40507）。"
            "请确认复制的是深圳燃气小程序请求头里的 CodeId；"
            f"原始响应: {detail}"
        )

    if code == 40510:
        return ShenzhenGasPermissionError(
            "当前 CodeId 与 accountChannelId 不匹配，接口拒绝访问（40510）。"
            "通常是 accountChannelId 配错，或 CodeId 已失效需要重新抓取；"
            f"原始响应: {detail}"
        )

    if msg and status == 200:
        return ShenzhenGasApiError(f"接口返回失败: {detail}")

    return ShenzhenGasApiError(f"API error: {detail} ({str(data)[:200]})")


def _parse_json(text: str):
    """Parse a JSON response body."""
    if not text:
        return {}

    return json.loads(text)
