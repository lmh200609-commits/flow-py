# Google Flow (Veo 3.1) 视频生成模型反代网关 - 多账号号池版 (Account Pool Edition)

将多个 Google Gemini Pro 会员账号在 **Google Flow** 中的视频生成能力（Veo 3.1 等）反向代理为本地 API 服务的轻量级中转站，**支持多账号号池与额度用尽自动无缝轮换 (Auto-Failover)**。

---

## 🌟 核心特性

- **多账号号池与自动故障转移 (Account Pool & Auto-Failover)**：
  - 支持录入无限个 Google Pro 账号，每个账号拥有独立的 Browser Profile 物理隔离。
  - **额度用尽自动切号**：当某个账号的点数用完或遇到风控限制时，系统自动将其标记为耗尽，并**无缝切换到下一个健康账号重试当前任务**，调用方完全无感！
  - **每日配额自动复苏**：耗尽账号在周期（默认24小时）结束后自动恢复为 Active 状态。
- **双向接入支持**：
  - **自定义 Agent**：通过标准 HTTP RESTful API（`/v1/video/generations`、`/v1/video/status/{task_id}`、`/v1/video/generate_sync`）直接调用。
  - **Codex 桌面集成**：已注册本地 Skill（`~/.codex/skills/google-flow-video`），Codex 在日常对话中可自动调度该服务出片。
- **真实会话与抗风控持久化**：
  - 内置 Playwright 反检测（去除 `navigator.webdriver` 标记，注入真实硬件与语言指纹，模拟自然键鼠交互），彻底突破 Google 异常活动拦截。
- **后台异步任务队列**：
  - 内置单并发任务调度队列，防止多 Agent 频繁请求导致 Google Web 界面冲突。
  - 支持同步等待与异步轮询两种调用模式。

---

## 👥 多账号号池管理 (CLI)

### 1. 查看当前号池状态与点数
```bash
py -3.11 account_manager.py list
```
输出示例：
```
================================================================================
ID         Name                   Status       Credits    Total Gen  Project URL
================================================================================
acc_01     Gemini Pro #1 (Default) active       1050       1          https://flow.google.com/project/...
acc_02     Gemini Pro #2 (Backup)  active       1050       0          https://flow.google.com/project/...
================================================================================
```

### 2. 交互式录入新账号（一键添加）
运行命令后，会自动弹出一个可见的独立 Chrome 窗口：
```bash
py -3.11 account_manager.py add --id acc_02 --name "Gemini Pro #2"
```
1. 在弹出的浏览器窗口中直接登录您的第 2 个 Google 账号并进入 Flow。
2. 脚本会自动侦测到您已进入项目工作区，自动提取配置并保存到号池中！
3. 重复此操作即可添加 3 号、4 号……实现大容量无限出片！

### 3. 手动复位账号状态
若某个账号额度刷新，可手动将其激活：
```bash
py -3.11 account_manager.py reset --id acc_01
```

---

## 🚀 启动反代网关服务

双击运行：
```powershell
D:\chatgpt聊天记录1\日常\flow-py\start_gateway.bat
```
或者在 PowerShell 终端执行：
```powershell
$env:PYTHONUTF8=1
cd "D:\chatgpt聊天记录1\日常\flow-py"
py -3.11 gateway.py
```
服务将在 `http://127.0.0.1:8765` 启动。

---

## 📡 API 接口参考

### 1. 查询号池全貌
- **请求**：`GET /v1/pool/accounts`
- **响应**：返回所有已注册账号的状态、各账号剩余点数与已出片统计。

### 2. 查询号池总可用点数
- **请求**：`GET /v1/credits`
- **响应**：返回所有活跃账号汇总的总可用点数。

### 3. 创建视频生成任务 (自动使用号池切号)
- **请求**：`POST /v1/video/generations`
- **Body**：
  ```json
  {
    "prompt": "太空中的宇航员在彩色星云前挥手，电影质感，4K高清",
    "model": "Veo 3.1 - Fast",
    "aspect_ratio": "16:9",
    "wait": false
  }
  ```
- **响应**：
  ```json
  {
    "task_id": "c1f7b880-...",
    "status": "queued",
    "check_url": "http://127.0.0.1:8765/v1/video/status/c1f7b880-..."
  }
  ```

### 4. 轮询任务状态
- **请求**：`GET /v1/video/status/{task_id}`
- **响应**（完成）：
  ```json
  {
    "task_id": "c1f7b880-...",
    "status": "completed",
    "used_account": "acc_01",
    "local_video_path": "D:/chatgpt聊天记录1/日常/flow-py/output/c1f7b880-....mp4",
    "download_url": "http://127.0.0.1:8765/files/c1f7b880-....mp4",
    "preview_url": "http://127.0.0.1:8765/files/c1f7b880-....png"
  }
  ```

---

## 🤖 接入自定义 Agent (`client_sdk.py`)

```python
from client_sdk import FlowVideoClient

client = FlowVideoClient("http://127.0.0.1:8765")

# 查看号池总点数
print("号池总点数：", client.get_credits())

# 提交视频生成任务（底层自动负载均衡与额度耗尽切号）
result = client.generate_video(
    prompt="一只可爱的小金毛在阳光下的草坪上打滚，写实风格，电影感",
    model="Veo 3.1 - Fast",
    wait=True
)

print("出片完成！由账号生成：", result["used_account"])
print("本地视频文件：", result["local_video_path"])
print("在线预览链接：", result["download_url"])
```
