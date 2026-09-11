# k-one-watch

只读监控 [HAIR STAGE K-ONE](https://airrsv.net/k-one111/calendar) 的 Air リザーブ 预约页，
在你指定的时间段一出现空位，就推到你手机上，你再自己去手动预约。

**这个工具只查不订。** 它从不提交任何预约、不填表、不碰你的个人信息 ——
通知里只给你一个链接，下单永远是你本人的动作。

跑在 GitHub Actions 上，**不需要你开着电脑**；同一份脚本也能在本机手动跑，方便调试和临时查一次。

```
【カット】9 个空位
  9/20(日) 11:00-12:00
  9/27(日) 12:00-14:00 / 15:00-16:00
  10/3(土) 11:00-12:00 / 16:00-17:00
  10/4(日) 13:00-14:00 / 17:00-18:00
  10/10(土) 17:00-18:00
```

## 快速上手

### 1. 拿一个推送渠道的 key

四个渠道任选，也可以配多个做双保险。**最省事的是 Bark。**

| 渠道 | 怎么拿 | 需要的环境变量 |
|---|---|---|
| **Bark**（iOS） | App Store 装 Bark，打开就能看到一个 URL | `BARK_URL`（形如 `https://api.day.app/AbCdEf123456`） |
| **Server酱·Turbo**（微信） | [sct.ftqq.com](https://sct.ftqq.com/) 微信扫码登录拿 SendKey | `SERVERCHAN_KEY` |
| **PushPlus**（微信） | [pushplus.plus](https://www.pushplus.plus/) 微信扫码拿 token | `PUSHPLUS_TOKEN` |
| **邮件** | Gmail 需要生成**应用专用密码**（不是登录密码） | `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASS` `SMTP_TO` |

一个都不配也能跑，只是结果只打印在终端里 —— 这种情况下**不会记录状态**，
所以你之后补上 key，当前这批空位仍会正常提醒你一次。

### 2. 填到 GitHub Secrets（云端 7×24 靠这个）

打开 **Settings → Secrets and variables → Actions → New repository secret**，
把上面用到的变量名和值加进去。

> 本仓库是公开的。密钥只能放 Secrets，**绝不要写进 `config.toml` 或任何会提交的文件**。

加完之后到 **Actions → watch → Run workflow** 手动点一次，确认手机能收到。
之后它每 15 分钟自动跑一轮。

### 3.（可选）本地也配一份

```bash
cp .env.example .env     # .env 已被 .gitignore 忽略
# 编辑 .env 填上同样的值
python watch.py test-notify
```

## 命令

需要 **Python 3.11+**（用到 `tomllib`），**零第三方依赖**，不用建虚拟环境、不用 `pip install`。

```bash
python watch.py check              # 抓取 → 比对 → 推送新空位（定时任务跑的就是这个）
python watch.py check --dry-run    # 只打印本轮会推什么，不推送、不写状态
python watch.py show               # 列出当前所有符合条件的空位
python watch.py show --all         # 连被过滤掉的也列出来，用于核对过滤条件
python watch.py test-notify        # 给已配置的渠道发一条测试消息
python -m unittest discover -s tests   # 跑单测（离线，用录好的响应快照）
```

## 配置

改 [`config.toml`](config.toml)，提交后云端下一轮自动生效。

```toml
[watch]
menus = ["s0000A5844"]      # 要监控的菜单，见下表
horizon_days = 28           # 从明天起往后看多少天
weekdays = ["sat", "sun"]   # 只要周末；写 [] 表示不限
hour_from = 10              # 空位开始时间 >= 10:00
hour_to = 18                # 空位开始时间 < 18:00
include_few_left = true     # △「残りわずか」也算空位

[notify]
title = "K-ONE 有空位"
booking_url = "https://airrsv.net/k-one111/calendar"
renotify_after_hours = 24   # 空位一直挂着时隔多久再提醒一次；0 = 只提醒一次
```

配置项写错（拼错键名、星期拼错、`hour_from >= hour_to`）会直接报错退出，
不会默默用错的值跑下去。

### 菜单 ID 对照表

| menuId | 菜单 | 时长 |
|---|---|---|
| `s0000A5844` | カット（剪发） | 60 分 |
| `s0000A5846` | カットコース | 60 分 |
| `s0000A5847` | カットシェーブ | 60 分 |
| `s0000C8FBB` | フルコース | — |
| `s0000C8FBD` | スカルプコース | — |
| `s0000C8FBE` | カラーコース | 90 分 |
| `s0000C8FBF` | 白髪ぼかしコース | — |
| `s0000C8FC1` | コールドコース（ロッド・ピンパーマ） | — |
| `s0000C8FC2` | ドライコース（アイロンパーマ） | — |

菜单时长会影响空位数量 —— 90 分的项目需要连续两个空档，所以空位天然比 60 分的少。

### 店铺作息

营业 **10:00–18:00**（14:00–15:00 休息），**周一、周二定休**，可预约窗口约 2 个月，
最早只能订明天。所以 `weekdays` 里写 `mon`/`tue` 不会有任何结果。

## 它是怎么工作的

页面是 Knockout.js 前端，真正的数据来自一个**无需登录**的 JSONP 接口：

```
GET https://airrsv.net/k-one111/stateful/calendar/staff/searchStaffMenuResrc
    ?menuId=<菜单ID>&bookingFromDt=YYYYMMDDhhmmss&bookingToDt=YYYYMMDDhhmmss&refineRange=&_=<ts>
```

- 响应是 `/**/callback({...})`，剥壳即 JSON
- `calendar.listModalIsActive[].isActive` 为 `true` 即可预约（页面就是用它决定格子能不能点）
- `calendar.listHourlyAvailabilityMark[].availabilityKbnCd`：`1`=○可预约 `2`=△残りわずか `3`=×不可
- **一次响应最多覆盖 7 天**，与请求区间多宽无关，所以要按周翻页
- 服务端会把请求窗口**夹到可预约期内**（请求 9/13 起的一周，实际返回 9/14–9/20），
  所以翻页游标按**实际返回的末日**推进，不能盲目按 7 天步进

对站点的负担：默认配置下约 4 次请求/轮 × 96 轮/天 ≈ 400 次/天，请求之间间隔 1.5 秒。
想再轻一点就调大 cron 间隔或调小 `horizon_days`。

状态记在 [`state/seen.json`](state/seen.json)：同一个空位只提醒你一次
（除非过了 `renotify_after_hours`）。空位被抢走后会从状态里移除，
所以要是别人取消、它重新放出来，你还会再收到一次提醒。

**没真正送达就不写状态** —— 全部渠道失败、或压根没配渠道，都不算通知过。
免得空位被记成"已通知"却其实没送到你眼前，从此永远漏掉。

## 两个已知的坑

1. **定时有延迟。** GitHub 的 `schedule` 实际触发常晚 5~15 分钟（高峰更久）。
   抢手档期可能慢半拍。要更准时（1 分钟级）可以把脚本搬到 Cloudflare Workers Cron。
2. **60 天后可能被自动停用。** GitHub 会把**仓库 60 天无活动**的定时工作流自动禁用。
   本项目的状态回写 commit 大概率能保活，但 GitHub 对机器人 commit 是否计入活动没有承诺。
   真被停了就去 **Actions → watch → Enable workflow** 点一下，或者随手推个 commit。

## 项目结构

```
watch.py                  CLI 入口
k_one/client.py           接口请求、JSONP 解包、重试、翻页范围
k_one/slots.py            解析 → 过滤 → 连续时段合并
k_one/config.py           config.toml 与 .env 加载（含校验）
k_one/state.py            去重：记住已通知过哪些空位
k_one/notify.py           Bark / Server酱 / PushPlus / 邮件 / 终端
tests/fixtures/           真实接口响应快照，单测全离线
.github/workflows/        watch.yml（定时监控）、ci.yml（单测）
```
