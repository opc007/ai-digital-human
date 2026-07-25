# 更新日志（CHANGELOG）

本项目的所有显著变更都会记录在这里。  
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### 新增
- 面向社区的 README、CONTRIBUTING、SECURITY、CODE_OF_CONDUCT
- GitHub Issue / PR 模板
- 基础 CI：敏感信息扫描 + 互动编排冒烟
- `models/.gitkeep`：明示模型权重不入库，遵循 `.gitignore`

### 改进
- `.gitignore`：屏蔽所有个人素材、运行期数据库 / 缓存 / 日志 / 模型权重
- `.env.example` 与 `src/broadcast/i2v_geeknow.py`：移除硬编码第三方网关默认值
- 控制台 `materials` 表单：默认 I2V 网关地址改为占位符

### 安全
- 任何含 Key / 推流码 / 个人素材的提交都会被 CI 拦截（gitleaks / 自定义 grep）

---

## [0.3.0] - 2026-07

### 新增
- Web 控制台：素材抽屉、配置抽屉、人物库（多角色 / 多造型）
- 图生视频待机（兼容 OpenAI 格式的视频网关）
- `runtime_mode`：云端 / 本地 / 混合三种模式切换
- 互动编排：队列、优先级、防刷、关键词审核、LLM 回复

### 改进
- FastAPI 路由分层，WebSocket 状态机解耦
- 控制台 UI 重写为抽屉式，新增快捷键 `Alt+0/1/S/Q//`

### 修复
- RTMP 重连在弱网下的若干边界场景
- 口型失败自动回退 ffmpeg 混流

---

## [0.2.0] - 2026-06

### 新增
- 多平台推流（抖音 / 快手 / 视频号 / 小红书 / TikTok）
- MuseTalk 外部脚本入口 + ffmpeg 回落
- 编排器状态机（`src/orchestrator/live.py`）

---

## [0.1.0] - 2026-05

### 新增
- MVP 跑通：脚本播报 + 半自动互动 + Web 控制台
- SQLite 持久化：用户 / 人设 / 房间 / 事件
- Docker Compose

---

## 版本号说明

- **Major**（X.0.0）：不兼容的架构变更
- **Minor**（0.X.0）：新增功能 / 模块，**保持兼容**
- **Patch**（0.0.X）：Bug 修复与文档更新