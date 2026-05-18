# Asset Monitor

自动化资产监控，通过 GitHub Actions 定时运行，结果推送到 QQ邮箱 → 微信通知。

## 监控任务

| 任务 | 频率 | 说明 |
|------|------|------|
| **VOO 200 SMA** | 每周五美股收盘后 | 对比 VOO 收盘价与 200 日均线，3% 缓冲带判断 |
| **沪深300 低PE选股** | 每月第一个交易日 | 筛选 CSI 300 中 PE 最低 10 只股票，附带 ROE |

## 配置

### 1. 启用邮件推送

在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：

| Secret | 说明 |
|--------|------|
| `SMTP_USER` | QQ 邮箱地址，如 `chenhaoze94@qq.com` |
| `SMTP_PASSWORD` | QQ 邮箱 SMTP 授权码（16位，非 QQ 密码） |

### 2. 获取 SMTP 授权码

QQ邮箱网页 → 设置 → 账户 → POP3/SMTP 服务 → 开启 → 生成授权码

### 3. 开启微信提醒

关注 "QQ邮箱提醒" 公众号，即可在微信收到邮件通知。

## 手动触发

在 GitHub Actions 页面，选择 workflow → Run workflow。

## 项目结构

```
├── .github/workflows/
│   ├── voo-200sma.yml       # VOO 每周监控
│   └── hs300-low-pe.yml     # A股每月选股
├── scripts/
│   ├── check_voo_200sma.py  # VOO 200 SMA 脚本
│   ├── hs300_low_pe.py      # 低PE选股脚本
│   └── send_email.py        # SMTP 邮件发送
└── README.md
```
