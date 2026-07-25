# AI 数字人直播 · 开源版（AI Digital Human Live）

<p align="center">
  <img src="docs/assets/promo-banner.jpg" alt="AI 数字人直播宣传海报" width="100%" />
</p>

<p align="center">
  <img src="docs/assets/promo-preview.gif" alt="数字人多造型预览" width="360" />
</p>

> 一句话：**一张照片 + 一段声音 → 一个会说话的 24h 数字人主播**，跑在本机或你自己的服务器上，RTMP 推到抖音 / 快手 / 视频号 / 小红书 / TikTok。

本仓库是 [AI 数字人 SaaS 平台](docs/AI数字人SaaS平台-开发文档.md) 的 **MVP 开源版**：
对话 / 声音 / 形象三件套都可以**云端 API** 或**本地模型**二选一，重点解决"个人 / 小团队花 1/5 成本、做出 90% 商用水准"的数字人直播需求。

- 🎯 目标用户：个人主播、小型 MCN、品牌方、独立开发者
- 💰 单小时运行成本估算 ~¥5（云端模式）
- 🧩 模块可替换：LLM / TTS / 口型 / 推流都能换成你喜欢的引擎
- 🌱 **欢迎共创**：提 Issue、加 PR、写文档、做插件，都会被认真 review

### 宣传物料（可直接转发）

| 文件 | 用途 |
|------|------|
| [docs/assets/promo-banner.jpg](docs/assets/promo-banner.jpg) | GitHub / 网页横版海报（含多造型） |
| [docs/assets/promo-banner-ai.jpg](docs/assets/promo-banner-ai.jpg) | 品牌主视觉横版海报 |
| [docs/assets/promo-poster-vertical.jpg](docs/assets/promo-poster-vertical.jpg) | 朋友圈 / 小红书竖版海报 |
| [docs/assets/promo-preview.gif](docs/assets/promo-preview.gif) | 四宫格动图预览 |
| [docs/assets/promo-preview.mp4](docs/assets/promo-preview.mp4) | 短视频预览（可再配旁白） |

---

## 目录

- [项目能做什么](#项目能做什么)
- [5 分钟跑起来](#5-分钟跑起来)
- [架构与目录](#架构与目录)
- [云端 vs 本地 vs 混合](#云端-vs-本地-vs-混合)
- [真模型接入](#真模型接入)
- [API 速览](#api-速览)
- [贡献与共建](#贡献与共建)
- [路线图](#路线图)
- [安全与隐私](#安全与隐私)
- [许可证](#许可证)

---

## 项目能做什么

| 能力 | 状态 | 说明 |
|------|------|------|
| 一键开播（脚本 / 互动双模式） | ✅ | 控制台选平台 → 一键推 RTMP |
| 多平台推流 | ✅ | 抖音 / 快手 / 视频号 / 小红书 / TikTok / 本机预览 |
| 云端对话（DeepSeek） | ✅ | 也支持任何 OpenAI 兼容接口 |
| 云端声音（MiniMax TTS） | ✅ | 也支持 edge-tts 等免费兜底 |
| 本地对话（Ollama） | ✅ | qwen2.5 等本地模型 |
| 口型（MuseTalk 外部脚本 + ffmpeg 回落） | ✅ | 未配置 GPU 时自动用动作视频混音 |
| 待机微动（图生视频） | ✅ | 任意 OpenAI 兼容视频网关 |
| 弹幕互动编排（队列 / 优先级 / 防刷 / 审核 / LLM） | ✅ | 见 `src/orchestrator/` |
| Web 控制台 | ✅ | 顶栏「素材 / 配置」抽屉式管理 |
| FastAPI + WebSocket + Swagger | ✅ | `/docs` 在线调试 |
| SQLite 持久化 | ✅ | 用户 / 人设 / 房间 / 事件 |
| Docker Compose | ✅ | 一键起服 |
| 真口型帧级低延迟 | 🟡 规划中 | 先以混流/外部脚本方案跑通 |
| 多租户 / 计费 / 平台对接 | 🟡 规划中 | SaaS 蓝图见 `docs/` |

---

## 5 分钟跑起来

> **不需要任何 Key 也能跑**：默认走"演示回复 + 静音演示音"，先看流程，再决定要不要接真模型。

### 方式 A：直接跑（macOS / Linux）

```bash
git clone <this-repo>
cd <this-repo>

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # 没有 Key 也行，先跑通

# 1) 环境自检
python scripts/00_check_env.py

# 2) 没素材时先生成纯色占位动作（仅联调用）
python scripts/make_placeholder_actions.py

# 3) 互动编排冒烟（不开 HTTP）
python scripts/08_smoke_interactive.py

# 4) 起控制台：浏览器打开 http://127.0.0.1:8100
python scripts/07_run_api.py
```

打开 http://127.0.0.1:8100 即可看到工作台：
- 左侧：数字人画面（未开播也显示 idle 形象）
- 右侧：选平台 → 填推流码 → 一键开播
- 下方：发弹幕，看数字人边说边动

快捷键：`Alt+0` 预览 · `Alt+1` 抖音 · `Alt+S` 开播 · `Alt+Q` 关播 · `Alt+/` 说明

### 方式 B：Docker

```bash
docker compose up --build
# 浏览器打开 http://127.0.0.1:8100
```

不需要 `.env` 也能起；首次进控制台「配置」抽屉填 Key 即可激活云端能力。

---

## 架构与目录

```text
                ┌──────────────┐
   用户/弹幕 ──▶│ Orchestrator │──▶ LLM（DeepSeek / Ollama / ...）
                │  (live.py)   │──▶ TTS（MiniMax / edge-tts / ...）
                │              │──▶ 口型（MuseTalk / ffmpeg 回落）
                └──────┬───────┘
                       │ RTMP / ffmpeg
                       ▼
              抖音 / 快手 / 视频号 / 小红书 / TikTok
```

```text
src/broadcast/        TTS / 口型 / 推流 / 批处理
src/engines/          LLM / 审核 / 动作匹配
src/orchestrator/     直播状态机（互动编排核心）
src/api/              FastAPI 路由 + WebSocket
src/db/               SQLite 模型
web/                  控制台前端（原生 HTML + JS，无构建步骤）
scripts/              CLI 工具（自检 / 播报 / 联调）
tools/                MuseTalk 入口、watchdog
configs/              配置（YAML，按目录拆分）
data/                 运行期产物（不入库，含 demo 元数据骨架）
docs/                 设计文档 / 路线图
```

更多架构与字段定义见 [`docs/`](docs/)：
- [MVP 技术规格（精简）](docs/MVP技术规格-精简版.md)
- [AI 数字人 SaaS 平台 · 完整开发文档](docs/AI数字人SaaS平台-开发文档.md)
- [ComfyUI 本机调试说明](docs/ComfyUI本机调试说明.md)

---

## 云端 vs 本地 vs 混合

控制台「配置」抽屉里直接选 **runtime_mode**，系统会按下面的组合自动调度：

| 模式 | 对话 | 声音 | 形象 | 适合 |
|------|------|------|------|------|
| 云端（cloud） | DeepSeek（云） | MiniMax（云） | MuseTalk / ffmpeg | 0 基础最快上手 |
| 本地（local） | Ollama（本地） | edge-tts 等 | MuseTalk / ffmpeg | 隐私优先，需要本机 GPU |
| 混合（hybrid） | DeepSeek（云） | MiniMax（云） | MuseTalk / ffmpeg | 兼顾效果与成本 |

> **没填 Key 时不会崩**：自动回退到"演示回复 + 静音演示音"，先看流程再升级。

---

## 真模型接入

把 `.env` 填好下面三组即可激活云端能力（其余留默认也能用）：

```bash
# ① 对话（任选其一；也支持任何 OpenAI 兼容网关）
DEEPSEEK_API_KEY=sk-...

# ② 声音
MINIMAX_API_KEY=...
MINIMAX_VOICE_ID=male-qn-qingse

# ③ 待机微动（图生视频，可选；用本机 ComfyUI 也可以）
VIDEO_I2V_BASE_URL=https://your-i2v-gateway.example/v1
VIDEO_I2V_API_KEY=sk-...
VIDEO_I2V_MODEL=doubao-seedance-1-5-pro_720p
```

### 本地对话（Ollama）

```bash
# 1) 装 Ollama：https://ollama.com
ollama pull qwen2.5:7b
# 2) 控制台切到「本地模式」，或在 .env 里写 OLLAMA_MODEL=qwen2.5:7b
```

### 口型（MuseTalk）

1. 克隆官方 / 自建 MuseTalk 到本机
2. `.env`：`MUSETALK_ROOT=...`
3. 工具脚本会尝试调用其 inference；失败自动 ffmpeg 混流

### 推流码

**永远不要**把推流码写进仓库或贴到 Issue 里。推荐做法：
- 控制台 → 配置 → 直接填 → 仅保存到本机 `.env`
- 进直播间 → 选平台 → 粘贴推流码 → 开播

---

## API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/login` | 登录（开发模式默认 `admin` / `admin`） |
| POST | `/api/v1/live/start` | 开播 |
| POST | `/api/v1/live/stop`  | 关播 |
| GET  | `/api/v1/live/{id}/status` | 状态 |
| POST | `/api/v1/live/{id}/input` | 注入弹幕 / 文本 |
| WS   | `/ws/live/{id}` | 实时事件流 |
| GET  | `/docs` | Swagger UI |

完整 Swagger：启动后访问 `http://127.0.0.1:8100/docs`。

---

## 贡献与共建

我们希望这个项目是一个**友好、低门槛、能跑得起来也能改得动**的社区项目，**不只是 demo**。

### 适合所有人参与的方向

- 🐛 提 Bug：哪个平台推流失败、哪个口型回退、哪条 API 报错 —— [Issue](../../issues)
- 📚 写文档：把"我第一次跑通"的过程补成《新人 5 分钟指南》
- 🌐 翻译 README / Docs：英文 / 日文 / 繁体，欢迎 PR
- 🎨 主题 / UI 优化：`web/styles.css`、`materials.css`
- 🧪 写测试：每个 `scripts/` 工具都能加单元测试
- 🔌 新引擎适配：
  - LLM：火山豆包 / 通义千问 / OpenAI / Claude
  - TTS：火山 / 阿里 / Azure / ElevenLabs
  - 口型：Sadtalker / LivePortrait / Wav2Lip
  - 推流：虎牙 / B 站 / YouTube Live

### 提 PR 之前的 Checklist

- [ ] `.env`、密钥、推流码、个人素材**没有**进入仓库（CI 会检查）
- [ ] 如果新增了配置项，在 `.env.example` 与 `configs/*.yaml` 留好默认值
- [ ] `python scripts/00_check_env.py` 与 `python scripts/08_smoke_interactive.py` 通过
- [ ] 在 PR 描述里写清楚「解决了什么 / 怎么验证 / 影响哪些模块」
- [ ] 大文件（模型权重 / 训练数据 / 视频）请用外链或 Release Assets，**不要**直接 commit

详细规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 路线图

- [x] MVP 跑通：脚本播报 + 半自动互动 + Web 控制台
- [x] 云端 / 本地 / 混合三种 runtime_mode
- [x] 多平台 RTMP 推流（5 大主流平台）
- [x] 待机微动 + 图生视频
- [ ] 帧级真口型（MuseTalk 模型权重集成）
- [ ] 多租户 / 计费 / 配额
- [ ] 多平台同播（一次开播推多个 RTMP）
- [ ] 弹幕自动抓取 + 跨平台汇总
- [ ] Web 端形象编辑器（拖拽 / 模板化）
- [ ] 形象 / 声音的"训练 + 克隆"轻量化工作流

详见 [`docs/AI数字人SaaS平台-开发文档.md`](docs/AI数字人SaaS平台-开发文档.md) 第十九章。

---

## 安全与隐私

- 🔒 **不要把任何 API Key、推流码、个人照片提交到仓库或 Issue / PR / Discussion**。
  提交前 `git status` 检查一下；实在手滑贴了，请立刻**轮换 Key**（多数平台都支持一键重置）。
- 🛡️ 安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要公开 Issue。
- 🧹 个人素材（照片、参考视频、原声）**已经在 `.gitignore` 里全部忽略**，但仍建议你在分享/截图前再检查一次。

---

## 许可证

本仓库使用 [MIT License](LICENSE)。

> 第三方服务的商标、模型权重与平台推流协议归各自方所有；本项目仅做工程集成，请在遵守各服务商 ToS 与当地法规的前提下使用。