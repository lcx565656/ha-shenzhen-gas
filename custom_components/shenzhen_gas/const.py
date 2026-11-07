DOMAIN = "shenzhen_gas"

CONF_CCB_CUST_NO = "ccb_cust_no"
CONF_METER_NO = "meter_no"
CONF_CODE_ID = "code_id"
CONF_UPDATE_INTERVAL_MINUTES = "update_interval_minutes"

# 旧版本把 accountChannelId 写死并存进配置项。现在渠道号一律由 CodeId 在请求时
# 自动解析、不落盘，这两个键只用于清理老配置项里的残留数据。
LEGACY_CONF_ACCOUNT_CHANNEL_ID = "account_channel_id"
LEGACY_CONF_CHANNEL_SOURCE = "account_channel_id_source"
LEGACY_KEYS = (LEGACY_CONF_ACCOUNT_CHANNEL_ID, LEGACY_CONF_CHANNEL_SOURCE)

PLATFORMS = ["sensor", "binary_sensor"]

# 默认轮询间隔（分钟），用户可在「配置」里改
DEFAULT_UPDATE_INTERVAL_MINUTES = 30
MIN_UPDATE_INTERVAL_MINUTES = 5
MAX_UPDATE_INTERVAL_MINUTES = 1440


def entry_data_without_legacy(data: dict, code_id: str) -> dict:
    """Return entry data with CodeId replaced and legacy keys dropped."""
    cleaned = {
        key: value for key, value in data.items() if key not in LEGACY_KEYS
    }
    cleaned[CONF_CODE_ID] = code_id

    return cleaned


def has_legacy_channel_data(data: dict) -> bool:
    """Return True if the entry still carries legacy accountChannelId keys."""
    return bool(set(LEGACY_KEYS) & set(data))
