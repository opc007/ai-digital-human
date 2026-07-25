<!--
感谢提交 PR！为了让大家更容易 review，请填写以下内容。
-->

## 解决了什么

<!-- 关联 Issue：Fixes #123 / Closes #456 -->
<!-- 一句话说明本次 PR 的目的 -->

## 改动概览

- 主要模块（`api` / `broadcast` / `orchestrator` / `engines` / `web` / `configs` / `docs` / `tools` / `scripts`）：
- 新增：
- 修改：
- 删除：

## 怎么验证

<!-- 你本地跑了哪些命令 / 看到什么效果 -->

```bash
# 例子
python scripts/00_check_env.py
python scripts/08_smoke_interactive.py
```

## 截图 / 录屏

<!-- 控制台改动建议附图 -->

## Checklist（必填）

- [ ] **没有把任何 API Key、推流码、个人素材加进仓库**
- [ ] 如果新增了配置项，`.env.example` 与对应 `configs/*.yaml` 已留默认值
- [ ] `python scripts/00_check_env.py` 通过
- [ ] `python scripts/08_smoke_interactive.py` 通过（如果改了互动编排）
- [ ] 大文件（模型权重 / 视频 / 训练数据）用外链或 Release，**没有** commit
- [ ] 标题用动词开头，正文贴了截图 / 日志 / 命令输出
- [ ] 已读过 [CONTRIBUTING.md](../CONTRIBUTING.md) 与 [SECURITY.md](../SECURITY.md)

## 影响范围 / 风险

<!-- 是否会影响现有用户；是否需要文档 / 配置同步更新 -->