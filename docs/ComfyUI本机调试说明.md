# 本机 ComfyUI + 5090 调试说明

## 你这台机器当前情况（已探测）

| 项 | 值 |
|----|-----|
| 显卡 | RTX 5090 D，约 32GB |
| ComfyUI | 已运行，**端口 8000**（不是默认文档里的 8188） |
| 安装 | Comfy Desktop + `D:\comfyuiwinwin` 模型库 |
| Wan 模型 | 已有 `wan2.1_i2v_480p_14B`、`wan2.2_*` 等 |
| 数字人控制台 | 改到 **8100**，避免和 Comfy 抢 8000 |

## 推荐用法（最简单）

### A. 先确认 Comfy 能连

1. 打开 **Comfy Desktop**，等界面加载完  
2. 浏览器访问：http://127.0.0.1:8000 （应能打开 Comfy 页面）  
3. 在项目里执行：

```powershell
cd C:\ai数字人
.\.venv\Scripts\Activate.ps1
python scripts/10_comfyui_debug.py
```

全部 `[OK]` 再往下。

### B. 数字人控制台

```powershell
python scripts/07_run_api.py
# 打开 http://127.0.0.1:8100
# 素材中心 http://127.0.0.1:8100/materials
```

在 **云端配置 / 素材中心** 确认：

```text
COMFYUI_BASE_URL=http://127.0.0.1:8000
```

### C. 生成动作视频

1. 素材中心 → 上传一张**正脸照片**  
2. 「本地生视频」→ 测试连接应显示在线  
3. 对 `wave` / `idle` 等点 **Comfy生成**  
4. 任务列表看进度；完成后回「形象与动作」预览  

或命令行短测（会占显存，首次加载 14B 较慢）：

```powershell
python scripts/10_comfyui_debug.py --smoke
```

### D. 手动更稳的路径（推荐正式素材）

1. 在 Comfy Desktop 里用蓝图 **Image to Video (Wan 2.2)** 自己跑  
2. 导出 mp4 → 素材中心 **上传视频** 到对应动作  
3. 不依赖 API 工作流也能开播  

## 工作流文件

项目已放默认 API 工作流：

```text
configs/comfyui/action_workflow.json
```

默认用 **Wan2.1 I2V 480p 14B**，短片段（约 33 帧、640×368）减轻显存压力。

若要换成你在 Comfy 里调好的图：

1. 在 Comfy 菜单 **Save (API Format)**  
2. 覆盖 `action_workflow.json`  
3. 把图片文件名改成 `__IMAGE__`，提示词改成 `__PROMPT__`  

## 常见问题

| 现象 | 处理 |
|------|------|
| 连接失败 | Comfy 是否已开；地址是否 8000 |
| 和控制台冲突 | 控制台用 8100，Comfy 用 8000 |
| 显存爆 | 减小 length/width；或改用 1.3B / fp8 模型改工作流 |
| 生成很慢 | 14B 正常，看 Comfy 窗口进度 |
| 只想开播 | 手动上传 mp4，不必等 Comfy |

## 建议调试顺序

1. `10_comfyui_debug.py` 连通  
2. 控制台一键体验（不依赖 Comfy）  
3. 上传真人照片  
4. Comfy 生成 1 个 `wave` 动作验证  
5. 再批量补 idle/nod 等  
6. 真推流  
