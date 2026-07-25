# AI 数字人 SaaS 直播平台 — 完整开发文档

> 版本：v1.0  
> 定位：**商用级**多租户 SaaS 平台  
> 目标用户：个人主播、MCN、品牌方  
> 核心卖点：**自建技术栈，成本是 Vidu S1 的 1/5，效果 90% 接近**

---

## 〇、文档导航

| 章节 | 内容 |
|------|------|
| 一 | 产品定位与商业模式 |
| 二 | 系统总体架构 |
| 三 | 核心模块设计 |
| 四 | 部署模式（本地/云端可切换） |
| 五 | 数据库与存储设计 |
| 六 | API 接口设计 |
| 七 | 客户端设计（Web + PC） |
| 八 | 多平台推流对接 |
| 九 | 数字人形象生成流程 |
| 十 | 预设动作库设计 |
| 十一 | 实时互动流程（核心） |
| 十二 | LLM / TTS / 口型引擎选型与接入 |
| 十三 | 弹幕抓取与处理 |
| 十四 | 调度器（编排核心） |
| 十五 | 监控、告警、日志 |
| 十六 | 成本与计费系统 |
| 十七 | 安全与合规 |
| 十八 | 性能指标与压测 |
| 十九 | 开发路线图（4 阶段） |
| 二十 | 风险与应急方案 |
| 附录 A | 环境与依赖清单 |
| 附录 B | 配置文件模板 |
| 附录 C | 关键代码骨架 |

---

## 一、产品定位与商业模式

### 1.1 产品形态

**多租户 SaaS 平台**，用户自助：
1. 注册账号
2. 上传 1 张真人照片
3. 上传 1 段声音（或用 TTS 默认音色）
4. 配置人设提示词
5. 绑定抖音/快手/视频号/小红书/TikTok 推流码
6. **一键开播**

### 1.2 商业模式

| 档位 | 月费 | 包含时长 | 适合 |
|------|------|----------|------|
| 体验版 | 免费 | 10 小时/月 | 试用 |
| 个人版 | 299 元/月 | 60 小时 | 个人主播 |
| 团队版 | 999 元/月 | 250 小时 | 小型 MCN |
| 企业版 | 3999 元/月 | 不限 | 品牌/MCN |
| 定制版 | 议价 | - | 大客户 |

**增值服务**：
- 形象定制：500 元/次
- 声音克隆：200 元/次
- 数字人 IP 授权：1000 元/年
- 私有化部署：10 万起

### 1.3 成本结构

**单直播间每小时成本**：

| 项 | 成本 | 备注 |
|----|------|------|
| 云 GPU（A10） | 2.5 元 | AutoDL/阿里云 |
| LLM（DeepSeek） | 0.3 元 | 云端 API |
| TTS（MiniMax） | 1.5 元 | speech-2.8 流式 |
| 推流带宽 | 0.5 元 | 5Mbps |
| 弹幕抓取 | 0.2 元 | 代理 IP |
| **合计** | **~5 元/小时** | |

**毛利率** = (卖价 - 5) / 卖价 ≈ **80%+**

---

## 二、系统总体架构

### 2.1 分层架构

```
┌─────────────────────────────────────────────────┐
│ 接入层  │  Web 后台 / PC 客户端 / 开放 API        │
├─────────────────────────────────────────────────┤
│ 网关层  │  Nginx + API Gateway + WAF + 限流     │
├─────────────────────────────────────────────────┤
│ 业务层  │  微服务（见下）                         │
├─────────────────────────────────────────────────┤
│ AI 引擎层 │ LLM / TTS / 口型 / 视频生成（可插拔） │
├─────────────────────────────────────────────────┤
│ 基础设施层 │ GPU 集群 / 对象存储 / 消息队列 / DB │
├─────────────────────────────────────────────────┤
│ 直播对接层 │ 抖音开放平台 / 快手 / 视频号 / ...  │
└─────────────────────────────────────────────────┘
```

### 2.2 微服务拆分

| 服务 | 职责 | 技术栈 |
|------|------|--------|
| `auth-service` | 登录/注册/鉴权 | Go + JWT |
| `user-service` | 用户/租户/计费 | Go + PostgreSQL |
| `persona-service` | 数字人形象/人设/声音 | Python + MinIO |
| `material-service` | 预设视频/动作库管理 | Python + MinIO |
| `live-service` | 直播间生命周期 | Go + Redis |
| `danmaku-service` | 弹幕抓取/分发 | Python + Kafka |
| `llm-service` | LLM 调用/提示词/记忆 | Python |
| `tts-service` | TTS 流式合成 | Python |
| `avatar-service` | 口型驱动/视频合成 | Python + GPU |
| `stream-service` | RTMP 推流 | C++/Go + FFmpeg |
| `billing-service` | 计费/订单/支付 | Go |
| `monitor-service` | 监控/告警/日志 | Go + Prometheus |
| `admin-service` | 运营后台 | Vue |

### 2.3 数据流（单条弹幕生命周期）

```
1. 弹幕抓取
   danmaku-service ──> Kafka (topic: danmaku_in)
2. 调度器
   live-service 消费 Kafka
   ├─> LLM 推理（异步）
   ├─> 文本返回后立即进 TTS 队列
3. TTS 流式输出
   tts-service ──> WebSocket ──> avatar-service
4. 口型驱动
   avatar-service 调用预设视频 + MuseTalk
   输出 H.264 流
5. 推流
   stream-service 推 RTMP 到直播平台
6. 计费
   实时上报时长到 billing-service
```

---

## 三、核心模块设计

### 3.1 模块清单

```
ai-digital-human-saas/
├── services/
│   ├── auth/              # 鉴权
│   ├── user/              # 用户
│   ├── persona/           # 形象/人设
│   ├── material/          # 素材库
│   ├── live/              # 直播编排（核心）
│   ├── danmaku/           # 弹幕
│   ├── llm/               # LLM
│   ├── tts/               # TTS
│   ├── avatar/            # 数字人驱动
│   ├── stream/            # 推流
│   ├── billing/           # 计费
│   └── monitor/           # 监控
├── clients/
│   ├── web/               # Vue3 管理后台
│   └── pc/                # Electron 客户端
├── sdk/
│   ├── python/            # Python SDK
│   └── node/              # Node SDK
├── workers/
│   ├── video-gen/         # Wan2.2 视频生成（离线）
│   └── lipsync/           # MuseTalk 口型（实时）
├── infra/
│   ├── docker/
│   ├── k8s/
│   └── terraform/
└── docs/
```

### 3.2 关键技术决策

| 项 | 选型 | 理由 |
|----|------|------|
| 后端语言 | **Go**（业务）+ **Python**（AI） | Go 高并发适合网关/计费，Python AI 生态成熟 |
| 数据库 | PostgreSQL 15 | 关系数据 + JSONB 灵活 |
| 缓存 | Redis 7 | 房间状态、限流 |
| 消息队列 | Kafka 3 | 弹幕峰值削峰 |
| 对象存储 | MinIO / 阿里云 OSS | 视频/音频文件 |
| GPU 调度 | Kubernetes + Volcano | 多租户隔离 |
| 实时通信 | WebSocket / gRPC | 内部服务调用 |
| 推流 | FFmpeg + RTMP | 业界标准 |

---

## 四、部署模式（本地/云端可切换）

### 4.1 三种部署模式

**用户可在 Web 后台一键切换**：

#### 模式 A：全云端（默认）
- 所有计算在云端
- 用户无需任何硬件
- 成本：~5 元/小时

```
用户客户端 ──> 云端全栈 ──> 直播平台
```

#### 模式 B：云端 AI + 本地推流
- LLM/TTS/口型在云端
- **推流在用户本地**（OBS 捕获云端画面）
- 优势：推流稳定，不依赖云端带宽
- 成本：~4.5 元/小时

```
云端 AI ──> 画面推送给用户 ──> 用户本地 OBS ──> 直播平台
```

#### 模式 C：本地全栈
- 用户需有 **RTX 4090/5090 + 32G 显存**
- LLM 用本地 Ollama
- TTS 用本地 GPT-SoVITS
- 口型用本地 MuseTalk
- **完全离线可用**
- 成本：电费 1～2 元/小时

**适用**：高隐私客户、批量直播间（>10 个）

### 4.2 部署模式配置文件

```yaml
# config/deployment.yaml
deployment:
  mode: cloud  # cloud | hybrid | local
  
  cloud:
    llm_endpoint: https://api.deepseek.com/v1
    tts_endpoint: wss://api.minimaxi.com/v1/t2a_v2
    avatar_endpoint: wss://avatar.internal/lipsync
    stream_endpoint: rtmp://push.internal/live/
    
  hybrid:
    llm_endpoint: https://api.deepseek.com/v1
    tts_endpoint: wss://api.minimaxi.com/v1/t2a_v2
    avatar_endpoint: wss://avatar.internal/lipsync
    stream_local: true   # 用户本地 OBS 推流
    
  local:
    llm_endpoint: http://localhost:11434/v1  # Ollama
    tts_endpoint: ws://localhost:9880         # GPT-SoVITS
    avatar_endpoint: ws://localhost:7860       # MuseTalk
    stream_local: true
```

### 4.3 模式切换实现

```python
# live-service/orchestrator.py
class Orchestrator:
    def __init__(self, room_id: str, mode: str):
        self.mode = mode
        if mode == "cloud":
            self.llm = CloudLLM(...)
            self.tts = CloudTTS(...)
            self.avatar = CloudAvatar(...)
        elif mode == "hybrid":
            self.llm = CloudLLM(...)
            self.tts = CloudTTS(...)
            self.avatar = CloudAvatar(...)
            self.stream = LocalStream()  # 区别
        elif mode == "local":
            self.llm = LocalLLM(...)
            self.tts = LocalTTS(...)
            self.avatar = LocalAvatar(...)
            self.stream = LocalStream()
```

---

## 五、数据库与存储设计

### 5.1 PostgreSQL 表结构（核心表）

```sql
-- 用户
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(128) UNIQUE,
    phone VARCHAR(20) UNIQUE,
    password_hash VARCHAR(128) NOT NULL,
    plan VARCHAR(20) DEFAULT 'trial',  -- trial/personal/team/enterprise
    status SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 数字人形象
CREATE TABLE avatars (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name VARCHAR(64) NOT NULL,
    gender VARCHAR(10),
    style VARCHAR(32),  -- realistic/anime/cartoon
    source_image_url TEXT,  -- 用户上传的原图
    reference_video_urls JSONB,  -- Wan2.2 生成的参考视频
    preview_url TEXT,  -- 预览图
    status SMALLINT DEFAULT 0,  -- 0生成中 1完成 2失败
    created_at TIMESTAMP DEFAULT NOW()
);

-- 声音克隆
CREATE TABLE voices (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name VARCHAR(64) NOT NULL,
    provider VARCHAR(20),  -- minimax/so-vits/fish-speech
    voice_id VARCHAR(64),  -- TTS 平台的 voice_id
    sample_url TEXT,  -- 原始音频
    status SMALLINT DEFAULT 0
);

-- 人设
CREATE TABLE personas (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    avatar_id BIGINT REFERENCES avatars(id),
    name VARCHAR(64),
    system_prompt TEXT NOT NULL,  -- 人设提示词
    greeting TEXT,  -- 开场白
    style_tags JSONB,  -- 风格标签
    temperature FLOAT DEFAULT 0.7,
    memory_enabled BOOLEAN DEFAULT FALSE,
    knowledge_base_id BIGINT
);

-- 预设动作库
CREATE TABLE action_presets (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,  -- wave, nod, thanks...
    category VARCHAR(32),  -- greeting/emotion/transition/idle
    video_url TEXT NOT NULL,
    duration_ms INT NOT NULL,
    thumbnail_url TEXT,
    is_public BOOLEAN DEFAULT TRUE,
    user_id BIGINT,  -- NULL=公共
    metadata JSONB
);

-- 直播间
CREATE TABLE live_rooms (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    avatar_id BIGINT REFERENCES avatars(id),
    persona_id BIGINT REFERENCES personas(id),
    title VARCHAR(128),
    platform VARCHAR(20),  -- douyin/kuaishou/xiaohongshu/wechat/tiktok
    rtmp_url TEXT,
    rtmp_key TEXT,
    deployment_mode VARCHAR(10),  -- cloud/hybrid/local
    status SMALLINT DEFAULT 0,  -- 0未开始 1直播中 2暂停 3结束
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INT DEFAULT 0,
    danmaku_count INT DEFAULT 0,
    gift_count INT DEFAULT 0
);

-- 直播记录
CREATE TABLE live_logs (
    id BIGSERIAL PRIMARY KEY,
    room_id BIGINT REFERENCES live_rooms(id),
    type VARCHAR(20),  -- danmaku/llm/tts/avatar/error
    payload JSONB,
    latency_ms INT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 计费
CREATE TABLE billings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    room_id BIGINT REFERENCES live_rooms(id),
    type VARCHAR(20),  -- duration/tts/llm/custom
    quantity INT,
    unit_price DECIMAL(10,4),
    amount DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 订单
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    plan VARCHAR(20),
    amount DECIMAL(10,2),
    pay_method VARCHAR(20),  -- alipay/wechat
    status SMALLINT DEFAULT 0,  -- 0待支付 1已支付 2已退款
    paid_at TIMESTAMP
);
```

### 5.2 Redis 实时状态

```
# 房间状态
live:room:{room_id}:state → JSON {mode, status, current_action, queue_length}
TTL: 24h

# 弹幕队列
live:room:{room_id}:danmaku_queue → LIST[danmaku_json]
TTL: 1h

# 限流
user:{user_id}:rate_limit → INT (每秒请求数)

# 分布式锁
live:room:{room_id}:lock → SETNX (防止重复开播)
```

### 5.3 对象存储结构

```
oss://ai-digital-human/
├── avatars/
│   └── {user_id}/
│       ├── source/         # 原始照片
│       ├── generated/      # Wan2.2 生成的动作视频
│       └── preview/        # 缩略图
├── voices/
│   └── {user_id}/
│       ├── sample/         # 原始录音
│       └── cloned/         # 克隆结果
├── actions/
│   └── public/             # 公共动作库
│       ├── greeting/
│       ├── emotion/
│       ├── transition/
│       └── idle/
├── live-recordings/        # 直播回放
│   └── {room_id}/
└── temp/
    └── {user_id}/          # 临时文件 24h 清理
```

---

## 六、API 接口设计

### 6.1 RESTful API

```
# 鉴权
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout

# 用户
GET    /api/v1/user/profile
PUT    /api/v1/user/profile
GET    /api/v1/user/usage        # 用量统计

# 数字人形象
POST   /api/v1/avatar/upload          # 上传照片
POST   /api/v1/avatar/generate        # 触发 Wan2.2 生成
GET    /api/v1/avatar/{id}
GET    /api/v1/avatar/list
DELETE /api/v1/avatar/{id}

# 声音
POST   /api/v1/voice/upload
POST   /api/v1/voice/clone
GET    /api/v1/voice/list

# 人设
POST   /api/v1/persona
GET    /api/v1/persona/{id}
PUT    /api/v1/persona/{id}

# 动作库
GET    /api/v1/actions                # 公共动作
POST   /api/v1/actions/custom          # 自定义动作
DELETE /api/v1/actions/{id}

# 直播
POST   /api/v1/live/start             # 开播
POST   /api/v1/live/stop              # 关播
POST   /api/v1/live/pause
GET    /api/v1/live/{id}/status
GET    /api/v1/live/{id}/logs

# 弹幕（WebSocket）
WS     /ws/live/{room_id}             # 实时弹幕

# 计费
GET    /api/v1/billing/usage
GET    /api/v1/billing/orders
POST   /api/v1/billing/recharge
```

### 6.2 WebSocket 协议

**客户端 → 服务端**：

```json
// 心跳
{"type": "ping", "ts": 1234567890}

// 手动输入
{"type": "text", "content": "你好"}

// 触发动作
{"type": "action", "name": "wave"}

// 配置调整
{"type": "config", "key": "temperature", "value": 0.8}
```

**服务端 → 客户端**：

```json
// AI 回复
{
  "type": "ai_response",
  "text": "欢迎来到直播间",
  "audio_url": "...",
  "video_url": "...",
  "action": "wave",
  "latency_ms": 1200
}

// 弹幕信息
{
  "type": "danmaku",
  "user": "张三",
  "text": "主播好漂亮",
  "gift": null
}

// 状态
{
  "type": "status",
  "state": "speaking",  // idle/reading/thinking/speaking
  "queue_length": 2
}
```

### 6.3 内部服务 gRPC

```protobuf
// proto/danmaku.proto
service DanmakuService {
  rpc PushDanmaku(DanmakuRequest) returns (Ack);
  rpc Subscribe(SubscribeRequest) returns (stream DanmakuEvent);
}

message DanmakuRequest {
  string room_id = 1;
  string user = 2;
  string text = 3;
  string gift = 4;
}
```

---

## 七、客户端设计（Web + PC）

### 7.1 Web 后台（Vue 3 + TypeScript）

**核心页面**：

```
/login                    登录
/register                 注册
/dashboard                总览
/avatars                  形象列表
  /create                 创建形象
    /upload               上传照片
    /generate             生成中
    /preview              预览确认
/voices                   声音列表
/personas                 人设列表
  /edit                   编辑人设
/actions                  动作库
/live                     直播列表
  /start                  开播配置
    /platform             平台选择
    /rtmp                 推流配置
    /preview              直播预览
  /monitor/{id}           实时监控
/billing                  计费
/settings                 设置
```

**关键页面：开播配置**

```vue
<template>
  <div class="live-start">
    <a-steps :current="step">
      <a-step title="选择形象" />
      <a-step title="选择人设" />
      <a-step title="选择平台" />
      <a-step title="推流配置" />
      <a-step title="预览" />
    </a-steps>
    
    <!-- Step 1: 形象 -->
    <div v-if="step === 0">
      <AvatarGrid v-model="form.avatar_id" />
    </div>
    
    <!-- Step 2: 人设 -->
    <div v-if="step === 1">
      <PersonaList v-model="form.persona_id" />
      <a-textarea v-model="form.greeting" placeholder="自定义开场白" />
    </div>
    
    <!-- Step 3: 平台 -->
    <div v-if="step === 2">
      <PlatformSelector v-model="form.platform" />
    </div>
    
    <!-- Step 4: 推流 -->
    <div v-if="step === 3">
      <a-input v-model="form.rtmp_url" placeholder="RTMP 地址" />
      <a-input v-model="form.rtmp_key" placeholder="推流码" />
      <a-select v-model="form.deployment_mode">
        <a-option value="cloud">全云端</a-option>
        <a-option value="hybrid">混合模式</a-option>
        <a-option value="local">本地模式</a-option>
      </a-select>
    </div>
    
    <!-- Step 5: 预览 -->
    <div v-if="step === 4">
      <LivePreview :config="form" />
    </div>
  </div>
</template>
```

### 7.2 PC 客户端（Electron）

**额外能力**（Web 没有的）：
- 本地 GPU 调用（MuseTalk）
- 本地推流（OBS 替代）
- 本地 LLM（Ollama）
- 系统通知
- 开机自启
- 多直播间同时管理

**技术栈**：Electron + Vue 3 + TypeScript + Rust（性能模块）

---

## 八、多平台推流对接

### 8.1 平台 RTMP 推流

| 平台 | 推流地址 | 鉴权 |
|------|----------|------|
| 抖音 | `rtmp://push-rtmp-fx.douyin.com/live/` | 推流码 |
| 快手 | `rtmp://push.kuaishou.com/live/` | 推流码 |
| 视频号 | `rtmp://wxalivepush.weixin.qq.com/live/` | 推流码 |
| 小红书 | `rtmp://push-redbook.xiaohongshu.com/live/` | 推流码 |
| TikTok | `rtmp://push-rtmp-fx.tiktok.com/live/` | 推流码 |

**注意**：所有平台推流码**需用户自己在平台后台获取**，我们不抓取（合规）。

### 8.2 推流服务实现

```python
# stream-service/pusher.py
import ffmpeg
import asyncio

class RTMPPusher:
    def __init__(self, room_id: str, rtmp_url: str, rtmp_key: str):
        self.url = f"{rtmp_url}/{rtmp_key}"
        self.process = None
        
    def start(self, video_input: str):
        """video_input 可以是文件、网络流、虚拟摄像头"""
        self.process = (
            ffmpeg
            .input(video_input, re=None)
            .output(
                self.url,
                vcodec='libx264',
                preset='ultrafast',
                tune='zerolatency',
                acodec='aac',
                b='5000k',
                maxrate='5500k',
                bufsize='10000k',
                g=60,
                f='flv'
            )
            .overwrite_output()
            .run_async()
        )
        
    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
```

### 8.3 推流稳定性保障

| 问题 | 方案 |
|------|------|
| 网络断 | 指数退避重连（最多 5 次） |
| 进程崩溃 | systemd / supervisor 自动重启 |
| 帧率不稳 | FFmpeg `-re` 参数控制 |
| 卡顿检测 | 监控推流码率，异常告警 |
| 多平台同时推 | 多进程并行，每平台独立推流 |

### 8.4 多平台同播

```python
class MultiPlatformPusher:
    def __init__(self, configs: List[Dict]):
        self.pushers = [
            RTMPPusher(c['room_id'], c['rtmp_url'], c['rtmp_key'])
            for c in configs
        ]
        
    def start_all(self, video_source: str):
        # 同一视频源，多 RTMP 输出
        # 方案：FFmpeg tee muxer
        outputs = [p.url for p in self.pushers]
        
        stream = (
            ffmpeg
            .input(video_source)
            .output(
                *outputs,
                # ... 编码参数
            )
        )
```

---

## 九、数字人形象生成流程

### 9.1 完整流程

```
1. 用户上传照片（1 张，正脸，高清）
   ↓
2. 检测照片质量（清晰度、角度、人脸检测）
   ↓
3. 预处理（裁剪、对齐、增强）
   ↓
4. Wan2.2 生成 20～30 个动作视频
   - 每个动作 3～5 秒
   - 540p 或 720p
   - 固定机位、背景、形象
   ↓
5. 视频后处理
   - 转码 H.264
   - 统一分辨率/帧率
   - 截取关键帧作缩略图
   ↓
6. 上传到 OSS
   ↓
7. 用户在 Web 端预览
   ↓
8. 确认完成 → 可开播
```

### 9.2 必备的 20 个动作

| 类别 | 动作名 | 用途 | 数量 |
|------|--------|------|------|
| **开场** | wave, bow, smile_hello | 开播欢迎 | 3 |
| **情绪** | happy, surprised, sad, shy, angry, thinking | 各种场景 | 6 |
| **互动** | nod, shake_head, clap, thumbs_up, heart | 回应用户 | 5 |
| **过渡** | look_away, look_back, lean_forward | 切换话题 | 3 |
| **感谢** | thanks_bow, thanks_heart, thanks_wave | 收礼物 | 3 |
| **总计** | | | **20** |

### 9.3 Wan2.2 生成提示词模板

```yaml
# action_prompts.yaml
actions:
  - name: wave
    category: greeting
    prompt: "A friendly person waving right hand, smiling, looking at camera, indoor setting, bright lighting, natural posture, 3 seconds"
    negative_prompt: "blurry, distorted face, extra fingers, deformed"
    camera: "fixed, front view"
    
  - name: bow
    category: greeting
    prompt: "A person bowing slightly, hands together, polite smile, looking at camera, indoor setting, 3 seconds"
    
  - name: thanks_heart
    category: thanks
    prompt: "A person making a heart gesture with both hands, sweet smile, eye contact, warm lighting, 3 seconds"
    
  - name: thinking
    category: emotion
    prompt: "A person with hand on chin, looking up slightly, thinking expression, indoor setting, 3 seconds"
    
  # ... 共 20 个
```

### 9.4 视频生成 Worker

```python
# workers/video-gen/main.py
import asyncio
from comfyui_client import ComfyUIClient
from oss_client import OSSClient

class VideoGenWorker:
    def __init__(self):
        self.comfy = ComfyUIClient(host="localhost:8188")
        self.oss = OSSClient()
    
    async def generate_actions(self, avatar_id: int, source_image_url: str):
        """为某个形象生成 20 个动作视频"""
        
        # 1. 下载原图
        image = await self.oss.download(source_image_url)
        
        # 2. 准备工作流
        actions = load_prompts("action_prompts.yaml")
        results = []
        
        for action in actions:
            # 3. 调用 ComfyUI（本地 5090 跑 Wan2.2）
            workflow = self.build_wan_workflow(
                image=image,
                prompt=action.prompt,
                negative=action.negative_prompt,
                duration=action.duration
            )
            video_path = await self.comfy.run(workflow)
            
            # 4. 上传 OSS
            url = await self.oss.upload(
                f"avatars/{avatar_id}/generated/{action.name}.mp4",
                video_path
            )
            
            results.append({
                "name": action.name,
                "url": url,
                "category": action.category
            })
            
            # 进度上报
            await self.report_progress(avatar_id, len(results), 20)
        
        return results
```

### 9.5 ComfyUI 工作流（Wan2.2）

工作流 JSON 文件（保存在 ComfyUI 中导出）：
- 输入：参考图像 + 动作提示词
- 模型：Wan2.2-Animate-14B
- 输出：5 秒 540p 视频

**关键参数**：
- 步数：20
- CFG：7
- 分辨率：960×540
- 帧率：25fps
- 总帧：125 帧（5 秒）

---

## 十、预设动作库设计

### 10.1 动作匹配规则

```python
# live-service/action_matcher.py
class ActionMatcher:
    def __init__(self):
        # 规则表
        self.rules = [
            # 礼物触发
            (Trigger.GIFT_LARGE, "thanks_bow"),
            (Trigger.GIFT_SMALL, "thanks_wave"),
            (Trigger.GIFT_SPECIAL, "thanks_heart"),
            
            # 弹幕触发
            (Trigger.WELCOME_USER, "wave"),
            (Trigger.PRAISE, "happy"),
            (Trigger.QUESTION, "thinking"),
            (Trigger.GOODBYE, "wave"),
            
            # 状态切换
            (Trigger.IDLE_30S, "look_away"),
            (Trigger.IDLE_60S, "thinking"),
            (Trigger.SCENE_CHANGE, "look_back"),
        ]
    
    def match(self, trigger: Trigger, context: Dict) -> str:
        """返回动作名"""
        for rule_trigger, action in self.rules:
            if trigger == rule_trigger:
                return action
        return "idle"
```

### 10.2 动作切换的平滑过渡

**问题**：从"挥手"切到"思考"会突兀。

**方案**：

```python
class ActionPlayer:
    def __init__(self):
        self.current_action = None
        self.next_action = None
        self.transition = False
    
    def play(self, action_name: str):
        """播放动作，必要时插入过渡"""
        if self.current_action and self.current_action != action_name:
            # 1. 播放淡出（200ms）
            self.play_fade_out()
            # 2. 切换动作
            self.current_action = action_name
            # 3. 播放淡入（200ms）
            self.play_fade_in()
        else:
            self.current_action = action_name
```

**过渡视频库**（必备）：

| 名称 | 时长 | 用途 |
|------|------|------|
| fade_to_thinking | 300ms | 切到思考 |
| fade_to_smile | 300ms | 切到笑 |
| idle_breathing | 2s | 循环播放（无动作时） |
| blink_loop | 3s | 眨眼循环 |

### 10.3 动作循环机制

```python
class IdleLoop:
    """无任务时循环播放 idle 视频"""
    
    IDLE_VIDEOS = [
        "idle_breathing_1.mp4",
        "idle_breathing_2.mp4",
        "idle_look_around.mp4",
        "blink_loop.mp4",
    ]
    
    def __init__(self):
        self.idx = 0
        self.current = None
    
    def next(self) -> str:
        video = self.IDLE_VIDEOS[self.idx]
        self.idx = (self.idx + 1) % len(self.IDLE_VIDEOS)
        return video
```

---

## 十一、实时互动流程（核心）

### 11.1 单条弹幕的完整时序

```
T+0ms   弹幕抓取（danmaku-service）
        │
T+50ms  进 Kafka
        │
T+100ms live-service 消费
        │
        ├─> 立即推 idle 视频（掩盖延迟）
        │
        ├─> LLM 调用（DeepSeek API）
        │   T+800ms 收到首个 token
        │
        ├─> 文本片段立即进 TTS 队列
        │   T+1000ms TTS 开始流式输出音频
        │
        ├─> 音频帧进 MuseTalk
        │   T+1200ms 开始输出口型视频
        │
T+1300ms 视频流推 RTMP
        │
        └─> 用户看到回复（端到端 1.3 秒）
```

### 11.2 调度器（核心）

```python
# live-service/orchestrator.py
import asyncio
from collections import deque

class LiveOrchestrator:
    def __init__(self, room_id: str, config: Dict):
        self.room_id = room_id
        self.config = config
        self.queue = asyncio.Queue(maxsize=100)
        self.state = State.IDLE
        self.current_task = None
        self.idle_player = IdleLoop()
        
        # 初始化各模块
        self.llm = LLMFactory.create(config['llm'])
        self.tts = TTSFactory.create(config['tts'])
        self.avatar = AvatarFactory.create(config['avatar'])
        self.pusher = RTMPPusher(...)
    
    async def run(self):
        """主循环"""
        self.pusher.start()
        
        # 启动推 idle 的后台任务
        idle_task = asyncio.create_task(self._idle_loop())
        
        # 启动弹幕消费
        consume_task = asyncio.create_task(self._consume_danmaku())
        
        await asyncio.gather(idle_task, consume_task)
    
    async def _idle_loop(self):
        """无任务时循环 idle"""
        while True:
            if self.state == State.IDLE:
                video = self.idle_player.next()
                await self.avatar.play_idle(video)
            await asyncio.sleep(0.1)
    
    async def _consume_danmaku(self):
        """消费弹幕队列"""
        while True:
            danmaku = await self.queue.get()
            asyncio.create_task(self._handle_danmaku(danmaku))
    
    async def _handle_danmaku(self, danmaku: Danmaku):
        """处理单条弹幕"""
        try:
            # 1. 状态机切换
            self.state = State.READING
            
            # 2. 选动作
            action = self.action_matcher.match(danmaku)
            
            # 3. 播放过渡视频（掩盖 LLM 延迟）
            if action:
                await self.avatar.play_action(action)
            
            # 4. LLM 流式推理
            self.state = State.THINKING
            full_text = ""
            async for text_chunk in self.llm.stream(danmaku.text):
                full_text += text_chunk
                # 不等 LLM 完成，立即送 TTS
                asyncio.create_task(self._synth_speech(text_chunk))
            
            # 5. 等 TTS 完成
            await self.tts.wait_done()
            
            # 6. 状态恢复
            self.state = State.IDLE
            
        except Exception as e:
            logger.error(f"handle danmaku error: {e}")
            self.state = State.IDLE
    
    async def _synth_speech(self, text: str):
        """流式合成"""
        async for audio_chunk in self.tts.stream(text):
            # 7. 立即送口型驱动
            async for video_chunk in self.avatar.lipsync_stream(audio_chunk):
                # 8. 推流
                await self.pusher.push_frame(video_chunk)
```

### 11.3 优先级队列

**问题**：用户问问题时，正在回复另一个问题，怎么办？

**方案**：

```python
class PriorityQueue:
    """多优先级弹幕队列"""
    
    PRIORITIES = {
        'gift_large': 100,   # 大礼物，最高
        'gift_small': 50,
        'danmaku': 10,        # 普通弹幕
        'idle': 0,            # 自动发言
    }
    
    def __init__(self):
        self.queues = {
            p: asyncio.Queue() for p in self.PRIORITIES
        }
    
    async def put(self, item):
        priority = self._calc_priority(item)
        await self.queues[priority].put(item)
    
    async def get(self):
        # 按优先级取
        for priority in sorted(self.queues.keys(), reverse=True):
            if not self.queues[priority].empty():
                return await self.queues[priority].get()
        return None
```

### 11.4 防刷屏策略

```python
class AntiSpam:
    """防止同一人连续发弹幕刷屏"""
    
    def __init__(self):
        self.user_last_msg = {}  # user_id -> timestamp
        self.user_msg_count = {}  # user_id -> count in window
    
    def should_process(self, danmaku) -> bool:
        user = danmaku.user_id
        now = time.time()
        
        # 1. 30 秒内同用户最多 3 条
        self.user_msg_count.setdefault(user, [])
        self.user_msg_count[user] = [
            t for t in self.user_msg_count[user] if now - t < 30
        ]
        if len(self.user_msg_count[user]) >= 3:
            return False
        self.user_msg_count[user].append(now)
        
        # 2. 同一用户 5 秒内不重复
        if user in self.user_last_msg and now - self.user_last_msg[user] < 5:
            return False
        self.user_last_msg[user] = now
        
        return True
```

---

## 十二、LLM / TTS / 口型引擎选型与接入

### 12.1 LLM 选型

| 模型 | 价格（每千 token） | 速度 | 推荐 |
|------|---------------------|------|------|
| **DeepSeek V3** | 输入 0.14 元 / 输出 1.1 元 | 快 | ⭐⭐⭐⭐⭐ |
| Qwen-Max | 输入 0.04 元 / 输出 0.12 元 | 快 | ⭐⭐⭐⭐ |
| GPT-4o-mini | 0.003 美元 | 快 | ⭐⭐⭐⭐ |
| MiniMax abab | 0.1 元 | 快 | ⭐⭐⭐ |

**推荐：DeepSeek V3**（中文强 + 便宜 + 速度快）

**提示词工程**：

```python
SYSTEM_PROMPT = """你是{name}，一名{age}岁的{style}主播。

【人设】
{persona}

【互动规则】
1. 回复简短（30字内），符合直播口吻
2. 收到礼物要感谢
3. 重复问题合并回答
4. 不确定的问题就幽默化解
5. 用"呢、呀、哦"等语气词
6. 偶尔用 emoji 但不要太多

【当前直播状态】
- 观众数：{viewer_count}
- 累计礼物：{gift_count}
- 已直播：{duration}
"""
```

### 12.2 TTS 选型

| 服务 | 质量 | 价格 | 延迟 | 推荐 |
|------|------|------|------|------|
| **MiniMax speech-2.8-turbo** | ⭐⭐⭐⭐⭐ | 0.1 元/万字符 | 流式 200ms | ⭐⭐⭐⭐⭐ |
| 火山引擎 TTS | ⭐⭐⭐⭐ | 0.05 元/万字符 | 流式 300ms | ⭐⭐⭐⭐ |
| 腾讯云 TTS | ⭐⭐⭐⭐ | 0.06 元/万字符 | 流式 400ms | ⭐⭐⭐ |
| 阿里云 TTS | ⭐⭐⭐ | 0.04 元/万字符 | 500ms | ⭐⭐⭐ |
| 本地 GPT-SoVITS | ⭐⭐⭐⭐ | 免费 | 100ms | ⭐⭐⭐⭐ |
| 本地 Fish-Speech | ⭐⭐⭐⭐ | 免费 | 200ms | ⭐⭐⭐⭐ |

**推荐：默认 MiniMax，本地模式用 Fish-Speech**

### 12.3 TTS 接入（MiniMax WebSocket）

```python
# tts-service/minimax_client.py
import websockets
import json
import asyncio

class MiniMaxTTS:
    def __init__(self, api_key: str, voice_id: str):
        self.url = "wss://api.minimaxi.com/v1/t2a_v2"
        self.api_key = api_key
        self.voice_id = voice_id
        
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """流式返回音频帧"""
        async with websockets.connect(self.url) as ws:
            # 配置
            await ws.send(json.dumps({
                "api_key": self.api_key,
                "voice_id": self.voice_id,
                "model": "speech-2.8-turbo",
                "stream": True,
                "format": "pcm",
                "sample_rate": 16000,
                "bitrate": 128000
            }))
            
            # 发送文本
            await ws.send(json.dumps({"text": text}))
            
            # 接收音频流
            while True:
                msg = await ws.recv()
                if isinstance(msg, bytes):
                    yield msg
                else:
                    data = json.loads(msg)
                    if data.get("is_final"):
                        break
```

### 12.4 口型驱动（MuseTalk）

```python
# avatar-service/musetalk_service.py
import torch
from musetalk import MuseTalkInference

class MuseTalkService:
    def __init__(self, model_path: str = "models/musetalk"):
        self.model = MuseTalkInference(model_path)
        self.model.to("cuda")
        
    async def lipsync_stream(
        self,
        reference_video: str,  # 基础视频（背景+人物）
        audio_chunks: AsyncIterator[bytes],  # TTS 音频流
    ) -> AsyncIterator[bytes]:
        """流式对口型，输出视频帧"""
        
        # 1. 提取参考视频特征
        face_features = self.model.extract_features(reference_video)
        
        # 2. 累积音频 buffer
        audio_buffer = b""
        frame_id = 0
        
        async for audio_chunk in audio_chunks:
            audio_buffer += audio_chunk
            
            # 每 40ms（25fps）输出一帧
            if len(audio_buffer) >= 640:  # 16kHz * 0.04s * 2 bytes
                # 3. 生成一帧
                frame = self.model.inference_step(
                    face_features,
                    audio_buffer[:640]
                )
                audio_buffer = audio_buffer[640:]
                
                # 4. 编码 H.264
                encoded = self.encode_h264(frame)
                yield encoded
                frame_id += 1
```

### 12.5 可插拔引擎接口

```python
# abstract interfaces
class LLMInterface(ABC):
    @abstractmethod
    async def stream(self, prompt: str, history: List) -> AsyncIterator[str]:
        pass

class TTSInterface(ABC):
    @abstractmethod
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        pass

class AvatarInterface(ABC):
    @abstractmethod
    async def play_action(self, name: str) -> bytes:
        pass
    
    @abstractmethod
    async def lipsync_stream(self, video: str, audio: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        pass

# Factories
class LLMFactory:
    _registry = {}
    @classmethod
    def register(cls, name, impl):
        cls._registry[name] = impl
    @classmethod
    def create(cls, config):
        return cls._registry[config['provider']](**config)
```

---

## 十三、弹幕抓取与处理

### 13.1 各平台弹幕抓取方案

| 平台 | 难度 | 方案 |
|------|------|------|
| 抖音 | 难 | 抖音直播伴侣 + WebSocket 逆向（灰色） |
| 抖音 | 中 | 抖音开放平台（有 API 但有限制） |
| 快手 | 中 | 快手开放平台 |
| 视频号 | 难 | 微信视频号助手 API |
| 小红书 | 难 | 需 APP 逆向 |
| TikTok | 中 | TikTok Live API |

**合规方案（推荐）**：

**不使用任何逆向手段**，而是：
1. **用户用 PC 直播伴侣**投影到电脑
2. **本机客户端** OCR 识别弹幕（屏幕识别）
3. 或 **手动输入**（运营/真人辅助）

**优点**：完全合规  
**缺点**：需要一台电脑

### 13.2 OCR 弹幕识别方案

```python
# danmaku-service/ocr_capture.py
import pytesseract
from PIL import Image
import mss

class OCRDanmaku:
    """屏幕 OCR 识别弹幕区域"""
    
    def __init__(self, region: Tuple[int, int, int, int]):
        """弹幕显示区域 (x, y, w, h)"""
        self.region = region
        self.sct = mss.mss()
    
    async def capture_loop(self):
        while True:
            # 1. 截屏
            screenshot = self.sct.grab(self.region)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra)
            
            # 2. OCR
            text = pytesseract.image_to_string(
                img,
                lang='chi_sim',
                config='--psm 6'
            )
            
            # 3. 去重 & 推队列
            for line in text.split('\n'):
                if self.is_new(line):
                    await self.queue.put(line)
            
            await asyncio.sleep(0.5)
```

### 13.3 弹幕数据结构

```python
@dataclass
class Danmaku:
    id: str
    user_id: str
    user_name: str
    text: str
    gift_name: Optional[str] = None
    gift_value: int = 0
    timestamp: float = 0.0
    platform: str = ""  # douyin/kuaishou/...
    
    @property
    def is_gift(self) -> bool:
        return self.gift_name is not None
    
    @property
    def priority(self) -> int:
        if self.gift_value >= 1000:
            return 100  # 大礼物
        elif self.gift_value > 0:
            return 50   # 小礼物
        return 10       # 普通弹幕
```

---

## 十四、调度器（编排核心）

### 14.1 状态机

```
                ┌──────────┐
        ┌──────→│   IDLE   │←─────────┐
        │       └────┬─────┘          │
        │            │ new danmaku    │ done
        │            ↓                │
        │       ┌──────────┐          │
        │       │ READING  │          │
        │       └────┬─────┘          │
        │            │ 200ms          │
        │            ↓                │
        │       ┌──────────┐          │
        │       │ THINKING │          │
        │       └────┬─────┘          │
        │            │ first audio    │
        │            ↓                │
        │       ┌──────────┐          │
        └───────│ SPEAKING │──────────┘
                └──────────┘
```

### 14.2 调度器实现

```python
# live-service/scheduler.py
class LiveScheduler:
    def __init__(self, room_id: str, config: Dict):
        self.room_id = room_id
        self.config = config
        self.state = State.IDLE
        self.action = None
        self.queue = PriorityQueue()
        self.orchestrator = LiveOrchestrator(room_id, config)
        
    async def run(self):
        asyncio.create_task(self._consume())
        await self.orchestrator.run()
    
    async def _consume(self):
        while True:
            danmaku = await self.queue.get()
            
            # 打断当前回复
            if self.state in [State.SPEAKING, State.THINKING]:
                # 检查是否高优先级
                if danmaku.priority >= 50:
                    await self._interrupt()
                else:
                    # 进队列等待
                    await self.queue.put(danmaku)
                    continue
            
            await self.orchestrator._handle_danmaku(danmaku)
```

### 14.3 打断机制

```python
class InterruptibleStream:
    """支持打断的流"""
    
    def __init__(self):
        self.interrupted = False
    
    async def stream(self):
        try:
            async for chunk in self._source():
                if self.interrupted:
                    break
                yield chunk
        finally:
            self.interrupted = False
    
    def interrupt(self):
        self.interrupted = True
```

---

## 十五、监控、告警、日志

### 15.1 监控指标

| 指标 | 阈值 | 告警 |
|------|------|------|
| LLM 响应时间 | >3s | 告警 |
| TTS 首包延迟 | >500ms | 告警 |
| 端到端延迟 | >3s | 严重 |
| 推流码率 | <4000kbps | 告警 |
| 推流断流次数 | >3/分钟 | 严重 |
| GPU 显存使用 | >90% | 告警 |
| 弹幕堆积 | >100 条 | 告警 |

### 15.2 Prometheus + Grafana

```python
# monitor-service/metrics.py
from prometheus_client import Counter, Histogram, Gauge

llm_latency = Histogram(
    'llm_latency_seconds',
    'LLM 响应延迟',
    buckets=[0.5, 1, 2, 3, 5]
)

tts_first_byte = Histogram(
    'tts_first_byte_seconds',
    'TTS 首包延迟'
)

end_to_end_latency = Histogram(
    'e2e_latency_seconds',
    '端到端延迟',
    buckets=[1, 2, 3, 5]
)

stream_bitrate = Gauge(
    'stream_bitrate_kbps',
    '推流码率',
    ['room_id']
)

errors_total = Counter(
    'errors_total',
    '错误总数',
    ['type']
)
```

### 15.3 日志规范

```python
import structlog

logger = structlog.get_logger()

# 结构化日志
logger.info(
    "danmaku_received",
    room_id=room_id,
    user=user_name,
    text=text,
    latency_ms=latency
)

logger.info(
    "ai_response",
    room_id=room_id,
    prompt_tokens=pt,
    completion_tokens=ct,
    llm_latency_ms=llm_ms,
    tts_latency_ms=tts_ms,
    e2e_latency_ms=e2e_ms
)
```

---

## 十六、成本与计费系统

### 16.1 实时计费

```python
# billing-service/metering.py
class Metering:
    """实时计量"""
    
    def __init__(self, user_id: int, room_id: int):
        self.user_id = user_id
        self.room_id = room_id
        self.start_time = time.time()
        self.total_chars = 0
        self.total_tokens = 0
    
    def on_tts(self, chars: int):
        self.total_chars += chars
        self._record('tts_chars', chars, unit_price=0.0001)  # 0.1元/万字符
    
    def on_llm(self, tokens: int):
        self.total_tokens += tokens
        self._record('llm_tokens', tokens, unit_price=0.0001)  # 0.1元/千token
    
    def on_tick(self):
        """每秒上报时长"""
        duration = int(time.time() - self.start_time)
        self._record('duration_seconds', 1, unit_price=0.0014)  # 5元/小时
    
    def _record(self, type_: str, qty: int, unit_price: float):
        Billings.create(
            user_id=self.user_id,
            room_id=self.room_id,
            type=type_,
            quantity=qty,
            unit_price=unit_price,
            amount=qty * unit_price
        )
```

### 16.2 套餐额度

```python
PLAN_QUOTAS = {
    'trial':      {'hours': 10,   'chars': 50000,    'tokens': 500000},
    'personal':   {'hours': 60,   'chars': 500000,   'tokens': 5000000},
    'team':       {'hours': 250,  'chars': 2000000,  'tokens': 20000000},
    'enterprise': {'hours': -1,   'chars': -1,       'tokens': -1},  # 不限
}
```

### 16.3 支付接入

- 支付宝（个人/企业）
- 微信支付
- 微信小程序支付
- 虎皮椒支付（个人可用）

---

## 十七、安全与合规

### 17.1 内容审核

**所有 AI 回复必须过审核**：

```python
# llm-service/content_moderation.py
class ContentModerator:
    def __init__(self):
        self.provider = AliGreen()  # 阿里云内容审核
    
    async def check(self, text: str) -> bool:
        result = await self.provider.check_text(text)
        return result.is_pass
    
    async def check_and_replace(self, text: str) -> str:
        """不通过则替换为安全回复"""
        if not await self.check(text):
            return "不好意思，这边换个话题聊~"
        return text
```

### 17.2 平台合规

| 平台 | 限制 |
|------|------|
| 抖音 | 数字人直播需报备，未报备可能封号 |
| 快手 | 需申请数字人权限 |
| 视频号 | 需企业认证 |
| 小红书 | 数字人暂不支持 |
| TikTok | 部分地区允许 |

**方案**：
- 在用户协议中明确告知合规风险
- 提供「合规模式」降低风险（保守话术）
- 主动引导用户报备数字人

### 17.3 数据安全

- 用户上传图片加密存储
- 推流码不存储（用户每次输入）
- 直播录像默认 7 天后删除
- GDPR / 个保法合规

### 17.4 鉴权

```python
# auth-service/middleware.py
async def auth_middleware(request, call_next):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return JSONResponse({"error": "未登录"}, status_code=401)
    
    try:
        user = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        request.state.user = user
    except jwt.ExpiredSignatureError:
        return JSONResponse({"error": "Token 过期"}, status_code=401)
    
    return await call_next(request)
```

---

## 十八、性能指标与压测

### 18.1 性能指标

| 指标 | 目标 | 极限 |
|------|------|------|
| 端到端延迟 | <2s | <3s |
| 首包延迟（TTS） | <500ms | <800ms |
| 推流稳定性 | 99.9% | 99.5% |
| 并发直播间 | 5/A10 | 10/A10 |
| 弹幕处理 | 100/秒 | 500/秒 |

### 18.2 压测方案

```python
# tests/load_test.py
import asyncio
import aiohttp

async def simulate_danmaku(room_id: str, count: int):
    """模拟高频弹幕"""
    async with aiohttp.ClientSession() as session:
        for i in range(count):
            async with session.post(
                f"http://localhost:8000/api/v1/live/{room_id}/inject",
                json={"text": f"测试弹幕 {i}", "user": f"user_{i}"}
            ) as resp:
                await resp.read()

# 运行：模拟 1000 条弹幕
asyncio.run(simulate_danmaku("room_1", 1000))
```

### 18.3 性能优化清单

| 项 | 优化 |
|----|------|
| LLM | 流式 + 首 token 优先 |
| TTS | WebSocket 长连接复用 |
| 口型 | TensorRT 推理 |
| 推流 | FFmpeg `-tune zerolatency` |
| 数据库 | 连接池 + 索引 |
| Redis | Pipeline 批量操作 |

---

## 十九、开发路线图（4 阶段）

### 阶段 1：MVP（4～6 周）

**目标**：单人单平台可直播

| 周 | 任务 |
|----|------|
| W1 | 架构设计、基础服务搭建 |
| W2 | Wan2.2 生成预设视频、MuseTalk 接入 |
| W3 | LLM + TTS 接入、流程跑通 |
| W4 | Web 后台 MVP、开播流程 |
| W5 | 推流到抖音、压测 |
| W6 | Bug 修复、内测 |

**可交付**：1 人可开播，单平台，功能简单

### 阶段 2：多平台 + SaaS 化（4～6 周）

| 周 | 任务 |
|----|------|
| W7 | 多平台推流、快手/视频号 |
| W8 | 用户系统、计费、支付 |
| W9 | PC 客户端、本地模式 |
| W10 | 内容审核、合规 |
| W11 | 监控、告警、运营后台 |
| W12 | 公测、修复 |

**可交付**：多平台商用基础版

### 阶段 3：优化（4 周）

| 周 | 任务 |
|----|------|
| W13 | 调度器优化、动作库扩展 |
| W14 | 直播录制、回放 |
| W15 | 数字人 IP 商店、声音克隆市场 |
| W16 | API 开放、SDK |

**可交付**：平台化、生态化

### 阶段 4：规模化（持续）

- 多 GPU 集群调度
- 数字人 IP 矩阵
- 跨语言（英文、日文）
- 海外市场（TikTok）

---

## 二十、风险与应急方案

| 风险 | 概率 | 影响 | 应急方案 |
|------|------|------|----------|
| 平台封禁 | 高 | 致命 | 多个平台分散，提供合规话术 |
| LLM 服务商涨价 | 中 | 高 | 多 LLM 备份（DeepSeek/Qwen/MiniMax） |
| GPU 涨价 | 中 | 中 | 多云厂商比价 + 提前囤卡 |
| TTS 故障 | 低 | 高 | 多 TTS 备份（MiniMax/火山） |
| 网络断流 | 中 | 中 | 多线路推流、自动重连 |
| 弹幕抓取失败 | 高 | 中 | OCR 备用 + 手动输入 |
| 政策变化 | 中 | 高 | 持续跟进，灵活调整 |

---

## 附录 A：环境与依赖清单

### A.1 服务器最低配置

| 角色 | CPU | 内存 | GPU | 磁盘 |
|------|-----|------|-----|------|
| 网关/API | 8 核 | 16G | - | 100G |
| 业务服务 | 16 核 | 32G | - | 200G |
| LLM 网关 | 8 核 | 16G | - | 100G |
| 数字人 GPU | 16 核 | 32G | A10 24G | 500G |
| 推流 | 8 核 | 16G | - | 200G |
| 数据库 | 16 核 | 64G | - | 1T SSD |
| Redis | 8 核 | 32G | - | 200G |
| Kafka | 16 核 | 32G | - | 2T |

**单直播间总成本** ~5 元/小时

### A.2 Python 依赖

```txt
# requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.32.0
websockets==13.1
asyncpg==0.30.0
redis==5.2.0
aiokafka==0.12.0
minio==7.2.8
boto3==1.35.0
openai==1.54.0  # 兼容 DeepSeek/Qwen
torch==2.4.1
torchvision==0.19.1
transformers==4.45.0
diffusers==0.31.0
musetalk==0.2.0  # 假设
ffmpeg-python==0.2.0
pillow==11.0.0
pytesseract==0.3.13
prometheus-client==0.21.0
structlog==24.4.0
```

### A.3 前端依赖

```json
{
  "dependencies": {
    "vue": "^3.5.0",
    "ant-design-vue": "^4.2.0",
    "pinia": "^2.2.0",
    "vue-router": "^4.4.0",
    "axios": "^1.7.0",
    "ws": "^8.18.0"
  }
}
```

---

## 附录 B：配置文件模板

### B.1 主配置 `config.yaml`

```yaml
app:
  name: ai-digital-human-saas
  env: production  # development/production
  debug: false

server:
  api_host: 0.0.0.0
  api_port: 8000
  ws_port: 8001

database:
  postgres:
    host: localhost
    port: 5432
    user: saas
    password: ${DB_PASSWORD}
    database: ai_saas
  
  redis:
    host: localhost
    port: 6379
    password: ${REDIS_PASSWORD}
    db: 0
  
  kafka:
    bootstrap_servers: localhost:9092
    topics:
      danmaku: danmaku_in
      llm_out: llm_out
      tts_out: tts_out

storage:
  oss:
    endpoint: oss-cn-shanghai.aliyuncs.com
    bucket: ai-digital-human
    access_key: ${OSS_ACCESS_KEY}
    secret_key: ${OSS_SECRET_KEY}

llm:
  default_provider: deepseek
  providers:
    deepseek:
      api_key: ${DEEPSEEK_API_KEY}
      base_url: https://api.deepseek.com/v1
      model: deepseek-chat
    qwen:
      api_key: ${QWEN_API_KEY}
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
      model: qwen-max
    openai:
      api_key: ${OPENAI_API_KEY}
      base_url: https://api.openai.com/v1
      model: gpt-4o-mini

tts:
  default_provider: minimax
  providers:
    minimax:
      api_key: ${MINIMAX_API_KEY}
      voice_id: female-shaonv
      model: speech-2.8-turbo
    volcano:
      app_id: ${VOLCANO_APP_ID}
      access_key: ${VOLCANO_ACCESS_KEY}

avatar:
  musetalk_model_path: models/musetalk
  device: cuda
  default_resolution: 540p

billing:
  plans:
    trial:
      price: 0
      hours: 10
    personal:
      price: 299
      hours: 60
    team:
      price: 999
      hours: 250
    enterprise:
      price: 3999
      hours: -1

monitor:
  prometheus_port: 9090
  alert_webhook: ${ALERT_WEBHOOK_URL}
```

### B.2 单用户配置

```yaml
# user-{user_id}/config.yaml
user:
  id: 12345
  plan: personal

avatar:
  id: 1
  source_image: oss://avatars/12345/source/photo.jpg
  actions:
    - wave
    - bow
    - thanks_heart
    # ...

voice:
  id: 1
  provider: minimax
  voice_id: female-shaonv

persona:
  name: 小美
  age: 25
  system_prompt: |
    你是小美，25岁甜美系主播...
  temperature: 0.7
  memory_enabled: false

live:
  default_platform: douyin
  default_deployment: cloud
  rtmp_url: rtmp://push-rtmp-fx.douyin.com/live/
  rtmp_key: ${USER_RTMP_KEY}
```

---

## 附录 C：关键代码骨架

### C.1 启动服务

```python
# main.py
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from services.auth import router as auth_router
from services.user import router as user_router
# ...

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    await init_db()
    await init_redis()
    await init_kafka()
    yield
    # 关闭
    await close_all()

app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(user_router)
# ...
```

### C.2 开播接口

```python
# services/live/router.py
from fastapi import APIRouter, Depends
from .orchestrator import LiveOrchestrator

router = APIRouter(prefix="/api/v1/live", tags=["live"])

@router.post("/start")
async def start_live(
    config: LiveConfig,
    user: User = Depends(get_current_user)
):
    """开播"""
    # 1. 校验
    if not user.has_quota():
        raise HTTPException(402, "额度不足")
    
    # 2. 校验推流码
    if not config.rtmp_key:
        raise HTTPException(400, "推流码不能为空")
    
    # 3. 创建房间
    room = await LiveRoom.create(
        user_id=user.id,
        **config.dict()
    )
    
    # 4. 启动编排器
    orchestrator = LiveOrchestrator(room.id, config.dict())
    asyncio.create_task(orchestrator.run())
    
    # 5. 启动计费
    metering = Metering(user.id, room.id)
    asyncio.create_task(metering.start())
    
    return {"room_id": room.id, "status": "started"}
```

### C.3 Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: ./services
    ports: ["8000:8000"]
    depends_on: [postgres, redis, kafka]
    environment:
      - DB_HOST=postgres
      - REDIS_HOST=redis
  
  postgres:
    image: postgres:15
    volumes: ["pg_data:/var/lib/postgresql/data"]
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
  
  redis:
    image: redis:7
    volumes: ["redis_data:/data"]
  
  kafka:
    image: bitnami/kafka:3.7
    environment:
      KAFKA_CFG_NODE_ID: 1
      KAFKA_CFG_PROCESS_ROLES: controller,broker
  
  avatar-gpu:
    build: ./workers/avatar
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  pg_data:
  redis_data:
```

### C.4 K8s 部署（GPU 节点）

```yaml
# k8s/avatar-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: avatar-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: avatar
  template:
    metadata:
      labels:
        app: avatar
    spec:
      containers:
      - name: avatar
        image: registry.internal/avatar:v1.0
        resources:
          limits:
            nvidia.com/gpu: 1
            nvidia.com/gpu.memory: 24Gi
        env:
        - name: CUDA_VISIBLE_DEVICES
          value: "0"
      nodeSelector:
        gpu: true
```

---

## 文档结束

**下一步建议**：

1. 立即：用 Wan2.2 生成 20 个测试动作视频
2. 本周：跑通 ComfyUI → MuseTalk → 推流 链路
3. 2 周内：完成 MVP 第一版
4. 1 个月：开始内测，2 个月商用

**关键里程碑**：
- W2：第一个完整的"弹幕 → 数字人回复"流程跑通
- W4：第一次实景直播测试
- W6：内测用户开播
- W8：正式商用上线

---

*文档版本：v1.0*  
*最后更新：2026-07-22*
