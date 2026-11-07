"""集成内部配置（内化，无需用户额外维护文件）。

这些都是**通用**配置：同一个深圳燃气小程序对所有用户都一样，所以直接写在
代码里作为默认值，用户装完即可用，不需要创建 ``.env`` 或设置环境变量。

如果需要修改（例如深圳燃气换了域名、小程序升版），改这里的常量即可。

个人敏感信息（CodeId / accountChannelId / 客户号 / 表号）**不在这里**：
它们由用户在 Home Assistant 网页表单里填写，只保存在本机
``config/.storage/core.config_entries``。

唯一因人而异的是「刷新间隔」，它放在集成的配置选项里（网页可改），
见 ``const.DEFAULT_UPDATE_INTERVAL_MINUTES`` 与 options flow。
"""

from __future__ import annotations

from dataclasses import dataclass

# 深圳燃气小程序 API 域名
BASE_URL = "https://wechat.szgas.com.cn"

# 小程序渠道类型（请求头 ChannelTye）
CHANNEL_TYPE = "WX_XCX"

# 深圳燃气小程序 appid 与版本号，用于拼 Referer
MINI_PROGRAM_APPID = "wx6188bb06271804e1"
MINI_PROGRAM_VERSION = "326"

# 模拟的小程序运行环境：Mac / Windows / iOS / Android
MINI_PROGRAM_ENV = "Mac"

USER_AGENT_TEMPLATE = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 MiniProgramEnv/{env} "
    "MicroMessenger/7.0.20"
)
USER_AGENT = USER_AGENT_TEMPLATE.format(env=MINI_PROGRAM_ENV)

# 获取 access_token 用的 client 凭据（小程序里内置的公开值）
TOKEN_CLIENT_ID = "test"
TOKEN_CLIENT_SECRET = "test"

# 单次请求超时（秒）
TIMEOUT = 20

# 请求头 HeaderNum 的随机上限
HEADER_NUM_MAX = 10


@dataclass(frozen=True)
class Settings:
    """运行时使用的通用配置。"""

    base_url: str = BASE_URL
    channel_type: str = CHANNEL_TYPE
    mini_program_appid: str = MINI_PROGRAM_APPID
    mini_program_version: str = MINI_PROGRAM_VERSION
    mini_program_env: str = MINI_PROGRAM_ENV
    user_agent: str = USER_AGENT
    token_client_id: str = TOKEN_CLIENT_ID
    token_client_secret: str = TOKEN_CLIENT_SECRET
    timeout: int = TIMEOUT
    header_num_max: int = HEADER_NUM_MAX

    @property
    def referer(self) -> str:
        """模拟小程序运行时页面地址。"""
        return (
            "https://servicewechat.com/"
            f"{self.mini_program_appid}/{self.mini_program_version}/page-frame.html"
        )


DEFAULT_SETTINGS = Settings()


def get_settings() -> Settings:
    """Return the built-in settings."""
    return DEFAULT_SETTINGS
