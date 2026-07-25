# ComfyUI 动作生成工作流

把你在 ComfyUI 里导出的 **API 格式** 工作流保存为：

```text
configs/comfyui/action_workflow.json
```

## 占位符（推荐）

在工作流 JSON 字符串中使用：

| 占位符 | 含义 |
|--------|------|
| `__IMAGE__` | 已上传到 ComfyUI 的参考图文件名 |
| `__PROMPT__` | 动作英文/中文提示词 |
| `__NEGATIVE__` | 负面提示词 |

控制台点「用 ComfyUI 生成」时会自动替换。

## 环境变量

在「云端配置」或 `.env` 中：

```text
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_PATH=   # 可选，自定义工作流路径
```

## 没有工作流时

仍可在「素材中心」**手动上传**已做好的 mp4 动作视频，不影响开播。
