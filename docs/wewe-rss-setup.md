# WeWe RSS 部署指南

本项目的自动监控依赖一个自托管的 **WeWe RSS** 实例来稳定获取微信公众号文章。

> WeWe RSS 基于**微信读书 API**（而非直接爬取公众号），稳定性远高于 Sogou/搜狗方案。
> 项目地址：https://github.com/cooderl/wewe-rss

---

## 1. 选择部署平台

推荐免费平台（任选其一）：

| 平台 | 免费额度 | 一键部署 |
|------|----------|----------|
| [Railway](https://railway.app) | 每月 $5 额度 | ✅ |
| [Render](https://render.com) | 750h/月 | ✅ |
| [Fly.io](https://fly.io) | 3 个免费实例 | ✅ |
| 自有 VPS | — | ✅ |

---

## 2. Railway 一键部署（推荐）

```bash
# 1. Fork wewe-rss 到你的 GitHub
# 2. 在 Railway 新建项目 → Deploy from GitHub repo → 选 wewe-rss

# 设置环境变量（Railway Dashboard → Variables）：
DATABASE_TYPE=sqlite
AUTH_CODE=你自己设的密码
SERVER_ORIGIN_URL=https://你的railway域名.railway.app
CRON_EXPRESSION=0 */6 * * *   # 每 6 小时更新一次
```

部署完成后记录你的域名，例如：`https://wewe-rss-production.up.railway.app`

---

## 3. Docker 本地部署（调试用）

```bash
docker run -d \
  --name wewe-rss \
  -p 4000:4000 \
  -e DATABASE_TYPE=sqlite \
  -e AUTH_CODE=yourpassword \
  -v $(pwd)/data:/app/data \
  cooderl/wewe-rss-sqlite:latest
```

访问 `http://localhost:4000`

---

## 4. 添加公众号订阅

1. 打开 WeWe RSS 管理界面
2. **账号管理** → **添加账号** → 微信扫码登录**微信读书**账号
   - ⚠️ 不要勾选「24小时后自动退出」
3. **公众号源** → **添加** → 粘贴任意一篇该公众号的**微信文章链接**

需要添加的公众号（参考 `wechat_accounts.json`）：

| 公众号名 | 说明 |
|----------|------|
| 字节跳动招聘 | 字节提前批/正式批公告 |
| 腾讯招聘 | 腾讯提前批/正式批公告 |
| 阿里巴巴招聘 | 阿里正式批公告 |
| 百度招聘 | 百度校招公告 |
| 美团招聘 | 美团北斗计划/正式批 |
| 华为招聘 | 华为正式批公告 |
| 小米招聘 | 小米校招公告 |
| 蔚来招聘 | 蔚来校招公告 |
| 小鹏汽车招聘 | 小鹏校招公告 |
| 理想汽车招聘 | 理想校招公告 |
| … | 参见完整列表 |

> 每次添加间隔 **30 秒以上**，避免触发风控。

---

## 5. 配置 GitHub Secrets

在 GitHub 仓库 → **Settings → Secrets and variables → Actions** 中添加：

| Secret 名 | 值 |
|-----------|----|
| `WEWE_RSS_BASE` | 你的 WeWe RSS 实例 URL，例如 `https://wewe-rss-production.up.railway.app` |
| `WEWE_RSS_TOKEN` | 你设置的 `AUTH_CODE`（可选，/feeds 路径默认无需鉴权） |

---

## 6. 验证

手动触发 GitHub Actions → **Daily WeChat Scrape** → 选择 `dry_run=true`，查看日志中是否有文章被匹配。

---

## 常见问题

**Q: 账号被封/进小黑屋怎么办？**
等待 24 小时自动解封。减少添加频率，或换一个微信读书账号。

**Q: 文章更新不及时？**
默认 Cron 为每 6 小时，可调整 `CRON_EXPRESSION`；GitHub Actions 每天 09:00 北京时间拉取。

**Q: 某公司公众号未被订阅？**
在 `wechat_accounts.json` 中找到对应行，手动在 WeWe RSS 管理界面添加一篇该公号的文章链接即可。
