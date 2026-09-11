"""K-ONE（HAIR STAGE K-ONE）Air リザーブ 预约空位监控。

只读工具：抓取公开的预约日历接口，发现空位就推送通知。
不会、也不应该用它提交任何预约。
"""

__all__ = ["client", "config", "notify", "slots", "state"]
