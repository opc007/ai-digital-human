# 动作视频生成说明（阶段 0）

本仓库**不绑定**某一版 ComfyUI 工作流文件；按你本机已安装的 Wan2.2 / 图生视频工具操作，产物放入约定目录即可。

## 1. 准备原图

1. 选 1 张**正脸、高清、光照均匀**的照片  
2. 复制到：

```text
data/avatars/demo/source/photo.jpg
```

## 2. 建议先生成的动作（3～5 个即可）

| 文件名 | 动作 | 用途 |
|--------|------|------|
| `idle.mp4` | 自然站立/微动 | 循环垫片 |
| `wave.mp4` | 挥手 | 开场 |
| `nod.mp4` | 点头 | 普通说话 |
| `thinking.mp4` | 思考 | 过渡（可选） |
| `thanks_wave.mp4` | 感谢挥手 | 收尾 |

参数建议（与 `configs/default.yaml` 对齐）：

- 分辨率：960×540 或 1280×720  
- 帧率：25fps  
- 时长：3～5 秒  
- 固定机位、同一背景与形象  

## 3. 输出路径

```text
data/avatars/demo/actions/idle.mp4
data/avatars/demo/actions/wave.mp4
...
```

## 4. 更新 meta.json

编辑 `data/avatars/demo/meta.json`，保证 `file` 与真实文件名一致，并填写大概 `duration_ms`。

## 5. 自检

```powershell
python scripts/00_check_env.py
```

看到各动作视频为 `[OK]` 即可进入口型/TTS 流水线。

## 6. 样片（W1 评审）

用任意剪辑工具或 ffmpeg 拼 3～5 分钟：

- 无声动作展示  
- 一段 TTS + 口型（或 mock 混音）  

输出建议：`data/output/sample_w1.mp4`，按任务拆解做去/留决策。
