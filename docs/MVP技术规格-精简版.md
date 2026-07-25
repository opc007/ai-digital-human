# MVP 技术规格（精简版）

> 范围：**阶段 0～2 结束时**应具备的最小产品（稳定播报 + 半自动互动）  
> 原则：能支撑开发与验收；**刻意少于**完整 SaaS 文档  
> 非目标：多租户计费、微服务网、多平台同播、PC 客户端、弹幕逆向

---

## 1. 产品范围

### 1.1 角色

| 角色 | 说明 |
|------|------|
| 运营 / 主播助手 | 配置文案或手动输入问题，开播、停播、插话 |
| 系统 | 单机或单 GPU 节点上的一套进程（可 Docker Compose） |

**暂无：** 多租户管理员、财务、开放 API 调用方。

### 1.2 用户故事（MVP 只认这些）

1. 作为运营，我能用**预设脚本**让数字人循环/顺序播报并推到直播平台。  
2. 作为运营，我能在网页**输入一条话术/模拟弹幕**，数字人回复并上镜。  
3. 作为运营，我能看到当前状态（idle / thinking / speaking）、队列长度、最近错误。  
4. 作为运营，我能**开始 / 停止**推流，停止后释放 GPU 相关任务。  

### 1.3 明确不做

- 注册套餐、支付、订单  
- 自动抓取抖音/快手弹幕（可预留接口）  
- 形象商店、声音市场  
- Kafka、K8s、多 GPU 调度  
- 五平台一键同播  

---

## 2. 系统架构（模块化单体）

```text
                    ┌──────────────┐
                    │  Web (Vue)   │
                    │  控制台      │
                    └──────┬───────┘
                           │ HTTP / WS
                    ┌──────▼───────┐
                    │  API 进程    │
                    │  FastAPI     │
                    │  orchestrator│
                    └──┬───┬───┬───┘
              ┌───────┘   │   └───────┐
              ▼           ▼           ▼
           LLM 适配    TTS 适配    控制信令
           (DeepSeek)  (MiniMax)      │
                                      ▼
                              ┌───────────────┐
                              │ GPU Worker    │  可同机另进程
                              │ lipsync+动作  │
                              └───────┬───────┘
                                      ▼
                              ┌───────────────┐
                              │ Stream        │
                              │ FFmpeg RTMP   │
                              └───────────────┘

存储：PostgreSQL（阶段 2 起）+ Redis（队列/状态）+ 本地/OSS 文件
阶段 0～1：可无 DB，仅 YAML + 文件
```

### 2.1 进程划分

| 进程 | 阶段 | 职责 |
|------|------|------|
| `api` | 2+ | HTTP/WS、编排、调 LLM/TTS |
| `worker-lipsync` | 1+ | 口型与视频帧/文件产出（GPU） |
| `stream` | 1+ | FFmpeg 推流（可与 worker 合并，稳定后再拆） |

阶段 1 允许 **单进程脚本**；阶段 2 建议 API 与 GPU 分离，避免推理堵住 HTTP。

### 2.2 可插拔接口（必须先定）

```python
# 伪代码 — 实现放 src/broadcast 或 src/engines

class LLMEngine(Protocol):
    async def stream(self, messages: list[dict]) -> AsyncIterator[str]: ...

class TTSEngine(Protocol):
    async def synth(self, text: str, voice_id: str) -> bytes: ...
    # 有流式则再加 stream()

class AvatarEngine(Protocol):
    async def speak(self, audio: bytes, action: str | None) -> Path: ...
    # 或异步任务 id；MVP 可用「产出 mp4 路径」

class StreamEngine(Protocol):
    def start(self, input_source: str, rtmp_url: str) -> None: ...
    def stop(self) -> None: ...
```

MVP 各接口 **只做一个实现**；配置用 `provider` 字段切换，避免写死厂商名满地跑。

---

## 3. 配置规格

### 3.1 全局 `configs/default.yaml`

```yaml
app:
  env: dev
  data_dir: data

server:                   # 阶段 2
  host: 0.0.0.0
  port: 8000

llm:
  provider: deepseek
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  # api_key 来自环境变量 DEEPSEEK_API_KEY

tts:
  provider: minimax
  model: speech-2.8-turbo
  default_voice_id: ""
  # MINIMAX_API_KEY

avatar:
  provider: musetalk
  device: cuda
  fps: 25
  width: 960
  height: 540
  model_path: models/musetalk

stream:
  video_bitrate: 4000k
  audio_bitrate: 128k
  reconnect_max: 5

moderation:               # 阶段 2
  enabled: true
  provider: keyword       # 先本地词库，再上云

limits:
  max_queue: 50
  max_reply_chars: 80
  user_msg_per_30s: 3
```

### 3.2 房间 `configs/rooms/{room_id}.yaml`

```yaml
room_id: demo
title: 演示直播间

avatar:
  dir: data/avatars/demo
  default_action: idle

persona:
  name: 小助手
  system_prompt: |
    你是直播间数字人助手。回复不超过30字，口语化，友善。
  greeting: 大家好，欢迎来到直播间。

tts:
  voice_id: ""            # 覆盖默认

stream:
  platform: douyin
  rtmp_url: rtmp://...    # 可环境变量覆盖
  # rtmp_key 禁止进仓库：用 env ROOM_DEMO_RTMP_KEY

script:                   # 阶段 1 播报用；阶段 2 可作兜底
  - id: open
    text: 大家好，欢迎来到直播间。
    action: wave
```

### 3.3 环境变量（`.env.example`）

```text
DEEPSEEK_API_KEY=
MINIMAX_API_KEY=
ROOM_DEMO_RTMP_KEY=
DATABASE_URL=postgres://...    # 阶段 2
REDIS_URL=redis://127.0.0.1:6379/0
```

---

## 4. 数据规格

### 4.1 阶段 0～1：文件即可

**`data/avatars/{avatar_id}/meta.json`**

```json
{
  "id": "demo",
  "name": "演示形象",
  "source_image": "source/photo.jpg",
  "actions": [
    {"name": "idle", "file": "actions/idle.mp4", "duration_ms": 3000, "category": "idle"},
    {"name": "wave", "file": "actions/wave.mp4", "duration_ms": 3000, "category": "greeting"},
    {"name": "nod", "file": "actions/nod.mp4", "duration_ms": 2500, "category": "emotion"}
  ]
}
```

### 4.2 阶段 2：PostgreSQL 最小表

只建 **真要查询/持久化** 的表。

```sql
-- 本地单用户也可用，便于以后扩展
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    username    VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE avatars (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id),
    name        VARCHAR(64) NOT NULL,
    root_path   TEXT NOT NULL,          -- 指向 data/avatars/...
    status      SMALLINT DEFAULT 1,   -- 1可用 0生成中 2失败
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE personas (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id),
    avatar_id   BIGINT REFERENCES avatars(id),
    name        VARCHAR(64),
    system_prompt TEXT NOT NULL,
    greeting    TEXT,
    temperature REAL DEFAULT 0.7
);

CREATE TABLE live_rooms (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id),
    avatar_id   BIGINT REFERENCES avatars(id),
    persona_id  BIGINT REFERENCES personas(id),
    title       VARCHAR(128),
    platform    VARCHAR(20),
    rtmp_url    TEXT,
    -- rtmp_key 不落库或加密短时缓存
    status      SMALLINT DEFAULT 0,   -- 0空闲 1直播中 2停止中
    started_at  TIMESTAMPTZ,
    ended_at    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE live_events (
    id          BIGSERIAL PRIMARY KEY,
    room_id     BIGINT REFERENCES live_rooms(id),
    type        VARCHAR(32),          -- input/llm/tts/error/state
    payload     JSONB,
    latency_ms  INT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_live_events_room ON live_events(room_id, created_at DESC);
```

**不做：** orders、billings、voices 多供应商表、action_presets 公共库大表（动作先看 meta.json）。

### 4.3 Redis 键（阶段 2）

```text
room:{id}:state     STRING  JSON  {status, phase, queue_len, updated_at}
room:{id}:queue     LIST    待处理输入 JSON
room:{id}:lock      STRING  开播锁，TTL 30s 续期
```

---

## 5. 编排与状态机

### 5.1 状态

```text
IDLE ──输入──► READING ──► THINKING ──► SPEAKING ──► IDLE
                  │                        │
                  └──── 可丢弃/合并 ────────┘
高优先级输入：允许打断 SPEAKING（MVP：完成当前句后插入，或直接 interrupt 标志）
```

| 状态 | 行为 |
|------|------|
| IDLE | 循环 idle 视频；消费队列 |
| READING | 解析输入、选 action、过防刷 |
| THINKING | LLM 流式；可先播过渡动作 |
| SPEAKING | TTS 完成段 + 口型 + 推流 |

### 5.2 输入优先级

| 类型 | priority | 说明 |
|------|----------|------|
| manual_urgent | 100 | 控制台「插播」 |
| gift_sim | 50 | 模拟礼物（阶段 2 可手选） |
| manual | 10 | 普通手动输入 |
| script | 0 | 脚本播报 |

### 5.3 防刷（手动输入也要）

- 同一 `user_key`：30s 内最多 3 条  
- 全局队列上限 `max_queue`，超出拒绝并提示  
- LLM 回复截断至 `max_reply_chars`  

### 5.4 端到端数据流（互动）

```text
WS/HTTP 输入
  → 入队 Redis
  → orchestrator 取出
  → moderation
  → LLM.stream → 拼全文（或分句）
  → moderation(回复)
  → TTS.synth
  → Avatar.speak(audio, action)
  → 通知 stream 切换当前片段 / 写入帧队列
  → live_events 记延迟
  → WS 推 status + ai_response
```

阶段 1 无 LLM：`script` → TTS → Avatar → Stream。

### 5.5 延迟指标（验收用，非宣传口径）

| 指标 | MVP 目标 |
|------|----------|
| 手动发送 → 进入 SPEAKING（有声或有口型画面） | ≤ 4s（理想 ≤ 3s） |
| 脚本模式段间黑屏 | ≤ 0.5s |
| 连续直播 | ≥ 1h（阶段 1 闸门） |

---

## 6. API 规格（阶段 2）

Base：`/api/v1`  
鉴权：MVP 可用 **单用户 Basic/Bearer 固定 Token**（`API_TOKEN`），不做完整注册也可先本地免鉴权（`env=dev`）。

### 6.1 HTTP

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/auth/login` | 可选；返回 token |
| GET | `/avatars` | 列表（读 DB 或扫描目录） |
| GET | `/avatars/{id}` | 详情 + actions |
| GET | `/personas` | 人设列表 |
| PUT | `/personas/{id}` | 更新 prompt/greeting |
| POST | `/live/start` | 开播 |
| POST | `/live/stop` | 关播 |
| GET | `/live/{room_id}/status` | 状态 |
| POST | `/live/{room_id}/input` | 注入文本（备用，非 WS） |
| GET | `/live/{room_id}/events` | 最近事件 |

#### `POST /live/start`

```json
// 请求
{
  "room_id": "demo",
  "persona_id": 1,
  "avatar_id": 1,
  "rtmp_url": "rtmp://...",
  "rtmp_key": "...",
  "mode": "interactive"   // script | interactive
}

// 响应
{
  "room_id": "demo",
  "status": "live",
  "ws_url": "ws://host:8000/ws/live/demo"
}
```

错误码：`400` 缺推流码，`409` 已在播，`503` GPU/worker 不可用。

#### `POST /live/{room_id}/input`

```json
{
  "text": "主播好",
  "user_key": "op1",
  "priority": 10,
  "action_hint": null
}
```

### 6.2 WebSocket ` /ws/live/{room_id}`

**客户端 → 服务端**

```json
{"type": "ping", "ts": 0}
{"type": "text", "content": "你好", "user_key": "op1"}
{"type": "action", "name": "wave"}
{"type": "interrupt"}
```

**服务端 → 客户端**

```json
{"type": "pong", "ts": 0}

{"type": "status", "phase": "idle|reading|thinking|speaking", "queue_length": 0}

{"type": "ai_response", "text": "你好呀", "action": "wave", "latency_ms": 2800}

{"type": "error", "code": "tts_failed", "message": "..."}
```

### 6.3 内部 Worker 接口（同机 HTTP 即可）

```text
POST /internal/lipsync
  body: { "job_id", "audio_path", "action", "avatar_id" }
  resp: { "job_id", "video_path" } 或 202 + 轮询

GET  /internal/jobs/{job_id}
```

不必上 gRPC；文件路径同机共享卷。

---

## 7. 动作与素材规则

### 7.1 MVP 动作集合（5～10）

| name | category | 触发 |
|------|----------|------|
| idle | idle | 默认循环 |
| wave | greeting | 开场、欢迎 |
| nod | emotion | 普通回复 |
| thinking | emotion | THINKING 过渡 |
| thanks_wave | thanks | 模拟礼物 / 感谢 |

生成可用 Wan2.2；**不强制**一次 20 个。

### 7.2 匹配（极简规则）

```text
if 输入带 gift 或 priority>=50 → thanks_wave
elif 状态进入 thinking → thinking（可并行准备）
elif 回复含 谢谢/感谢 → thanks_wave
else → nod 或 wave（随机/配置）
```

### 7.3 视频约定

- 编码：H.264 + AAC（最终推流）  
- 中间件：统一 fps、分辨率，避免拼接跳动  
- idle：可无缝循环；长度 2～5s 多段轮换更佳  

---

## 8. LLM / TTS / 审核

### 8.1 LLM

- 厂商：DeepSeek OpenAI 兼容接口  
- 历史：MVP **仅保留最近 4～6 轮**，防止膨胀  
- 系统提示：人设 +「≤30 字、直播口语」  

### 8.2 TTS

- 默认 MiniMax；失败重试 2 次  
- 缓存：相同 `voice_id+text` 哈希缓存文件，省费用  

### 8.3 审核

1. 本地敏感词（输入 + 输出）  
2. 不通过：回复固定话术「咱们换个话题哈～」  
3. 预留云审核 provider 接口  

---

## 9. 推流规格

| 项 | MVP 建议 |
|----|----------|
| 协议 | RTMP |
| 视频 | H.264，3～5 Mbps 可配 |
| 音频 | AAC 128k |
| 关键参数 | 低延迟预设；输入节奏可控 |
| 密钥 | 环境变量；日志打码 |
| 重连 | 最多 5 次指数退避 |
| 平台 | **先 1 个**（如抖音测试号） |

多平台：同一阶段不实现 tee 多推。

---

## 10. Web 控制台（阶段 2 最小页）

| 路由 | 功能 |
|------|------|
| `/login` | 可选 |
| `/` | 房间状态、开播/关播 |
| `/live/:id` | 输入框、队列、日志、相位 |
| `/persona` | 编辑 system_prompt / greeting |

技术：Vue3 + 任意 UI 库；**不做**完整开播 5 步向导也可，用表单一次提交。

---

## 11. 部署（MVP）

### 11.1 Docker Compose（阶段 2）

```text
services:
  api:        # FastAPI
  worker:     # lipsync GPU — runtime: nvidia
  postgres:
  redis:
  # 无 kafka
```

阶段 1：本机 Python + FFmpeg 即可。

### 11.2 资源

| 角色 | 建议 |
|------|------|
| 开发机 | 4090 24G + 32G RAM |
| 磁盘 | ≥ 200G（模型+视频） |

---

## 12. 目录与代码映射

```text
src/
  api/                 # 阶段 2：routes, ws, deps
  orchestrator/        # state machine, queue consumer
  engines/
    llm/
    tts/
    avatar/
    stream/
  moderation/
  models/              # SQLAlchemy / SQL 模型
scripts/               # 阶段 0～1 CLI
web/                   # 控制台
configs/
data/
```

---

## 13. 测试与验收

### 13.1 自动化（能写尽写）

| 用例 | 说明 |
|------|------|
| config 加载 | 缺字段报错清晰 |
| 队列优先级 | gift 先于 manual |
| 防刷 | 超限拒绝 |
| 审核 | 脏词替换 |
| health | 200 |

### 13.2 手工验收

| 编号 | 场景 | 通过标准 |
|------|------|----------|
| A1 | 脚本开播 1h | 无不可恢复中断 |
| A2 | 连续手动 20 条输入 | 均有回复或明确拒绝 |
| A3 | 开播中改人设再发言 | 新 prompt 生效（或文档约定需重启） |
| A4 | 关播再开播 | 资源释放，可第二次开播 |
| A5 | 错误推流码 | 明确错误，不假死 |

### 13.3 非功能

- 密钥不进 Git、不进明文日志  
- GPU OOM 有错误事件，不默默卡死  

---

## 14. 里程碑与规格对应

| 阶段 | 规格启用范围 |
|------|----------------|
| 0 | 素材 meta 约定、样片验收 |
| 1 | 配置、脚本流、TTS/Avatar/Stream、推流、无 DB API |
| 2 | 状态机、HTTP/WS、DB 最小表、Redis、审核、控制台 |
| 3+ | 见完整开发文档；本规格不展开 |

---

## 15. 与完整开发文档的差异摘要

| 完整文档 | 本 MVP 规格 |
|----------|-------------|
| 12 微服务 | 1～3 进程单体 |
| 完整计费订单 | 无 |
| 20 动作 + 多平台 | 5～10 动作 + 1 平台 |
| 弹幕抓取多种方案 | 仅手动/HTTP 注入 |
| 端到端 1.3s | 验收 3～4s |
| Go+Python 混合 | 先 Python 打通 |
| Kafka | Redis 列表 |

完整文档在 **阶段 3～4** 按需裁剪升级，避免一次性实现。

---

## 16. 开放问题（实现前拍板即可）

1. 口型输出是「整段 mp4 切换」还是「帧级管道」？（MVP 推荐 **整段 mp4**，实现快）  
2. TTS 是否必须流式？（MVP 允许非流式短句）  
3. 推流机与 GPU 是否同机？（同机简单；异机要共享存储或拉流）  
4. 第一平台定哪家测试号？  

拍板后写入 `configs/default.yaml` 注释，避免开发中来回改。

---

*文档版本：v1.0 · 与《阶段0-1任务拆解》配套 · 覆盖至半自动互动 MVP*
