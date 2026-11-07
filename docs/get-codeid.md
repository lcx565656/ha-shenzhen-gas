# 获取 CodeId 教程

本集成目前需要填写深圳燃气微信小程序请求头里的 `CodeId`。`CodeId` 一般长期不变，只需要获取一次；真正会定期过期的是接口 `access_token`，集成会自动刷新。

## 准备

推荐使用电脑上的微信和抓包工具获取。下面以 Charles / Proxyman / mitmproxy 这类工具为例，任选一个即可。

你需要准备：

- 电脑微信
- 一个 HTTPS 抓包工具
- 深圳燃气微信小程序已登录并绑定燃气账户

## 步骤

1. 打开抓包工具，并开启 HTTPS 解密。
2. 在电脑微信里打开“深圳燃气”小程序。
3. 进入账单、余额、用气记录等任意会加载账户数据的页面。
4. 在抓包工具里过滤域名：

   ```text
   wechat.szgas.com.cn
   ```

5. 找到任意 `/api/` 开头的请求。
6. 查看请求头，复制 `CodeId` 的值。

常见请求示例：

```text
https://wechat.szgas.com.cn/api/newcis/homepage/getBillDate
https://wechat.szgas.com.cn/api/handle/gasBill/getUserBillDataInfo
https://wechat.szgas.com.cn/api/handle/network/queryDayData
```

请求头里会有类似下面的字段：

```text
CodeId: o3Qsf5xxxxxxxxxxxxxxxxxxxxxx
accountChannelId: 123456789
```

只需要复制 `CodeId` 冒号后面的完整值，填入 Home Assistant 集成配置页的 `CodeId`。

`accountChannelId` **不用填**：集成会用 `CodeId` 调
`/api/handle/fraccountchannel/findAccountByOpenID` 自动解析出来，每次请求现取现用，
不写进配置项。

## 这两个值分别是什么

| 字段 | 含义 |
| --- | --- |
| `CodeId` | 微信小程序登录后的 `openid`，标识"你是哪个小程序用户" |
| `accountChannelId` | 该 openid 在小程序里的渠道账号 id，标识"你能看哪个账号的数据" |

深圳燃气的业务接口会同时校验这两个值。只带 `CodeId` 而 `accountChannelId` 不对时，
接口返回 `40510 无权限访问！`；`CodeId` 本身无效时返回 `40507 没有查询到对应的渠道信息`。

旧版本集成把一个固定的 `accountChannelId` 写死了，所以除原作者以外的人都会遇到
40510。当前版本改为按 `CodeId` 自动解析，并会清掉旧配置项里残留的渠道号字段。

## 注意事项

- 不要把 `CodeId` 发给别人，它可以访问你的燃气账户数据。
- `CodeId` 不是 OAuth token，通常不会频繁变化。
- 如果更换微信号、重新绑定深圳燃气账户，或小程序账号异常，可能需要重新获取。
- 如果抓包里看不到 HTTPS 内容，请确认抓包工具的根证书已经安装并信任。

## 为什么不能只填客户号？

深圳燃气的部分业务接口会校验 `CodeId`。实测同一个接口、同一个客户号：

- 不带 `CodeId`：返回 `HTTP 500 页面加载失败`。
- 带 `CodeId` 但 `accountChannelId` 不匹配：返回 `40510 无权限访问！`。
- 两者都正确：正常返回数据。

所以当前版本仍需要用户手动获取一次 `CodeId`。
