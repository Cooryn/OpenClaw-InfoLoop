# OpenClaw-InfoLoop

> **AI 驱动、人机协同的内容运营引擎** — 从信息发现到微信公众号发布的一站式工作流。

---

## 📖 项目简介

**InfoLoop** 是 [OpenClaw](https://github.com/openclaw) 生态中的内容运营技能包，为内容团队提供一条从「信息雷达扫描 → AI 摘要 → 人工筛选 → 长文扩写 → 微信公众号发稿 → 趋势追踪」的完整闭环流水线。

核心设计理念：

- **Human-in-the-Loop（人机协同）** — AI 负责发现、摘要和初稿，人类负责筛选、审核和最终决策。
- **技能声明式架构** — 每个功能以 *skill* 形式注册在 `manifest.yaml`，可被 OpenClaw 运行时动态调度。
- **LLM 优雅降级** — 所有依赖大模型的步骤均内置确定性回退逻辑，即使 API 不可用也不会中断流水线。

---

## ✨ 功能模块

| 模块 | 文件 | 说明 |
| --- | --- | --- |
| **Web Radar（信息雷达）** | `skills/web_radar.py` | 抓取指定 URL 列表的网页内容，解析标题、分类、正文和发布日期；支持关键词过滤；调用 Qwen 大模型生成 ~100 词摘要 |
| **Mail Notifier（邮件推送）** | `skills/mail_notifier.py` | 将摘要列表渲染为带索引编号的精美 HTML 邮件，通过 SMTP 发送给运营人员；用户可直接在 OpenClaw 对话中以 `[1]`、`[2]` 引用选题 |
| **Content Studio（内容工坊）** | `skills/content_studio.py` | 根据用户选中的索引，将原始素材扩写为不少于 800 字的微信长文；支持自动上传封面图、创建公众号草稿 |
| **Trend Analyzer（趋势预测）** | `skills/trend_analyzer.py` | 对当日全部文本语料进行实体识别与关键词提取，输出次日监控策略，形成「采 → 编 → 发 → 追」闭环 |

---

## 🏗️ 工作流架构

```
                        ┌──────────────────┐
                        │   Web Radar      │
                        │  fetch_articles   │
                        │  summarize_articles│
                        └────────┬─────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │ Mail Notifier    │
                        │ send_digest_email │
                        └────────┬─────────┘
                                 │
                          用户浏览邮件摘要
                          在对话中选择 [1] [3]
                                 │
                                 ▼
                        ┌──────────────────┐
                        │ Content Studio   │
                        │ expand_content    │
                        │ post_to_wechat    │
                        └────────┬─────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │ Trend Analyzer   │
                        │ generate_trend    │
                        │ _report           │
                        └──────────────────┘
                                 │
                          输出次日监控策略
                          反馈到下一轮 Web Radar
```

---

## 🚀 快速开始

### 环境要求

- Python ≥ 3.10
- (可选) 通义千问 / DashScope API Key
- (可选) 微信公众号 AppID & AppSecret
- (可选) SMTP 邮箱账号

### 1. 克隆仓库

```bash
git clone https://github.com/your-org/OpenClaw-InfoLoop.git
cd OpenClaw-InfoLoop
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的实际配置：

```dotenv
# 通义千问 / DashScope API
QWEN_API_KEY=your_qwen_api_key_here
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# 微信公众号（可选）
WECHAT_APP_ID=your_wechat_app_id_here
WECHAT_APP_SECRET=your_wechat_app_secret_here
WECHAT_AUTHOR=InfoLoop Bot

# SMTP 邮件推送（可选）
SMTP_HOST=smtp.example.com
SMTP_USER=your_smtp_user_here
SMTP_PASS=your_smtp_password_here
TARGET_EMAIL=recipient@example.com

# 代理（可选）
PROXY_URL=http://127.0.0.1:7890
```

### 4. 独立运行各模块（快速验证）

```bash
# 信息雷达
python -m skills.web_radar

# 邮件推送
python -m skills.mail_notifier

# 内容扩写
python -m skills.content_studio

# 趋势分析
python -m skills.trend_analyzer
```

---

## 🧪 运行测试

```bash
pytest
```

测试覆盖了所有四个技能模块的核心逻辑，不需要真实的 API Key 或 SMTP 服务器即可执行。

---

## 📁 项目结构

```
OpenClaw-InfoLoop/
├── config/
│   └── manifest.yaml          # OpenClaw 技能声明清单
├── skills/
│   ├── __init__.py
│   ├── web_radar.py           # 信息发现与 AI 摘要
│   ├── mail_notifier.py       # 摘要邮件推送
│   ├── content_studio.py      # 长文扩写与微信发稿
│   └── trend_analyzer.py      # 趋势分析与次日监控策略
├── tests/
│   ├── conftest.py
│   ├── test_web_radar.py
│   ├── test_mail_notifier.py
│   ├── test_content_studio.py
│   └── test_trend_analyzer.py
├── .env.example               # 环境变量模板
├── .gitignore
├── requirements.txt           # Python 依赖
└── README.md                  # 本文件
```

---

## 📋 技能清单 (manifest.yaml)

项目通过 `config/manifest.yaml` 向 OpenClaw 运行时声明所有可用工具：

| 工具名称 | 函数签名 | 用途 |
| --- | --- | --- |
| `fetch_articles` | `web_radar.fetch_articles(urls, keywords?)` | 从 URL 列表抓取候选文章 |
| `summarize_articles` | `web_radar.summarize_articles(raw_data)` | 为文章生成 AI 摘要 |
| `send_digest_email` | `mail_notifier.send_digest_email(summarized_json)` | 发送带索引的 HTML 摘要邮件 |
| `expand_content` | `content_studio.expand_content(selected_indices, full_cache)` | 扩写为公众号长文 |
| `post_to_wechat` | `content_studio.post_to_wechat(title, content)` | 创建微信公众号草稿 |
| `generate_trend_report` | `trend_analyzer.generate_trend_report(all_daily_text)` | 生成趋势报告与次日策略 |

---

## ⚙️ 技术细节

### LLM 集成

- 使用 [通义千问（Qwen）](https://dashscope.aliyuncs.com/) 作为默认大模型，通过 OpenAI 兼容接口调用。
- 所有 LLM 调用内置 **3 次重试 + 指数退避**，并提供无 LLM 的确定性回退输出。
- 支持通过 `CONTENT_STUDIO_MODEL` 为长文生成单独指定模型。

### 网络弹性

- HTTP 请求基于 `requests.Session`，挂载 `HTTPAdapter` 实现自动重试（针对 429 / 5xx 状态码）。
- 代理配置优先级：`PROXY_URL` → `HTTP_PROXY`。

### 微信公众号

- 支持通过环境变量直接指定 `WECHAT_COVER_MEDIA_ID`，或指定本地图片路径由程序自动上传。
- 文章内容自动转换为微信兼容的 HTML 格式。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'feat: add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 提交 Pull Request

---

## 📄 许可证

本项目尚未指定开源许可证，请联系项目维护者了解使用条款。
