# 贡献指南（CONTRIBUTING）

欢迎一起来把这个项目做得更好 🙌。  
无论你是第一次提 PR 的新手，还是做过多年开源的老炮儿，都欢迎贡献代码、文档、设计、测试、Issue 回复。

---

## 0. 先读一下

- [README.md](README.md)：项目能做什么、怎么跑起来
- [docs/](docs/)：架构与设计说明
- [SECURITY.md](SECURITY.md)：遇到安全问题怎么报告

提 Issue / PR 之前，请确保已经读完以上三处（至少 README）。

---

## 1. 我可以贡献什么？

### 1.1 不写代码也能贡献

- 🐛 **提 Bug**：哪个平台推流失败？哪条 API 报错？把复现步骤、报错截图贴到 Issue
- 📚 **写文档**：把你"第一次跑通"的过程补成《新人 5 分钟指南》
- 🌐 **翻译**：英文 / 日文 / 繁体 README
- 🎨 **UI / 主题建议**：截图 + 文字描述即可
- 💬 **回复 Issue**：很多 Issue 是别人遇到和你一样的问题，能帮一句也是贡献

### 1.2 写代码的方向

- 🧩 **新引擎适配**：LLM / TTS / 口型 / 推流
  - LLM：火山豆包 / 通义千问 / OpenAI / Claude / Groq
  - TTS：火山 / 阿里 / Azure / ElevenLabs
  - 口型：Sadtalker / LivePortrait / Wav2Lip
  - 推流：虎牙 / B 站 / YouTube Live
- 🎛 **控制台改进**：`web/` 目录下是原生 HTML + JS，没有构建步骤，改完直接刷新即可
- 🧪 **测试**：每个 `scripts/*.py` 工具都欢迎加单元测试
- ⚙️ **配置体验**：让用户少填字段、错误更友好
- 📦 **打包**：Docker 多阶段、镜像瘦身、依赖收敛

---

## 2. 提 Issue

### Bug Report

请在 Issue 里说清楚：

1. 你想做什么
2. 实际发生了什么
3. 怎么复现（命令 / 控制台操作 / 截图）
4. 系统与版本：`python --version` / 操作系统 / 浏览器
5. 相关日志（去掉密钥后再贴！）

### Feature Request

请说明：

1. 你要解决的场景 / 痛点
2. 你期望的交互方式
3. 有没有参考项目 / 截图
4. 你愿意贡献吗？（愿意的话我们直接对接）

---

## 3. 提 PR

### 3.1 Fork & Clone

```bash
# 1. Fork
# 2. Clone 你的 fork
git clone https://github.com/<you>/<this-repo>.git
cd <this-repo>
git remote add upstream https://github.com/<owner>/<this-repo>.git
```

### 3.2 新建分支

```bash
git checkout -b feat/your-feature
# 或 fix/your-bug、docs/your-doc
```

### 3.3 本地先跑通

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python scripts/00_check_env.py
python scripts/08_smoke_interactive.py
```

### 3.4 修改代码

- 保持现有目录结构与命名风格
- 公共函数写 docstring，类型尽量标注
- 不要顺手把无关文件一起改了（小 PR 更容易被 review）

### 3.5 Commit 信息

```
<type>(<scope>): <subject>

<body>

<footer>
```

**type**：`feat` / `fix` / `docs` / `style` / `refactor` / `test` / `chore` / `perf`  
**scope**：`api` / `broadcast` / `orchestrator` / `engines` / `web` / `configs` / `docs` ...

示例：

```
feat(broadcast): 支持 Edge-TTS 作为云端兜底声音

- 在 settings_store 新增 USE_FREE_TTS 字段说明
- 控制台「配置」抽屉新增开关
- 解决未填 MINIMAX_KEY 时完全没有声音的体验问题

Closes #123
```

### 3.6 PR 提交前 Checklist

- [ ] **没有把任何 Key / 推流码 / 个人素材加进仓库**（CI 会扫，但自己也 `git status` 看一下）
- [ ] 如果新增了配置项，`.env.example` 与对应 `configs/*.yaml` 已留默认值
- [ ] `python scripts/00_check_env.py` 通过
- [ ] `python scripts/08_smoke_interactive.py` 通过（如果改了互动编排）
- [ ] 大文件（模型权重 / 视频 / 训练数据）请用外链或 Release，**不要** commit
- [ ] PR 描述里写清楚：解决了什么 / 怎么验证 / 影响哪些模块
- [ ] 标题用动词开头；正文贴截图 / 日志 / 命令输出

### 3.7 Review 流程

- 维护者会在 3 个工作日内回复（首次 review）
- 小改动通常 1~3 轮 review 后合并
- 大改动（重构、新引擎、新模块）会先开个 RFC Issue 讨论方向

---

## 4. 行为准则

请阅读 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

> 简单版：友善、就事论事、不人身攻击；任何骚扰行为会被零容忍处理。

---

## 5. 开发约定速查

- Python 3.10+；类型注解 + dataclass / pydantic
- 控制台前端：原生 HTML + JS + CSS，不引 npm 构建（方便大家改）
- 配置：YAML 在 `configs/`，运行期可热改的密钥在 `.env`
- 状态机：`src/orchestrator/live.py`，新交互先在这里落点
- TTS / 口型 / 推流都在 `src/broadcast/`，每个引擎一个文件 + 工厂方法

---

## 6. 找不到方向？

直接开 Issue 写"我想贡献但不知道从哪开始"，我们一起挑一个适合你的 issue 🛠。