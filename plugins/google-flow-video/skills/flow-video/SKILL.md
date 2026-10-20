---
name: flow-video
description: 使用 Google Flow (Veo 3.1) 生成高质量电影级视频。当用户提出生成视频、制作视频短片、动画或动漫片段时调用本技能。
---

# Google Flow Video Plugin

本技能由 `google-flow-video` 插件提供，利用底层 Google Flow (Veo 3.1) 多账号中转号池生成高质量视频。

## 用户使用方式

当用户要求生成视频时，定位到本插件目录下的 `scripts/flow_generate.py` 并执行：

```bash
python "<插件根目录>/scripts/flow_generate.py" "<视频描述提示词>" "<画面比例: 16:9 或 9:16>"
```

脚本将全自动处理以下过程：
1. 向上游网关提交任务。
2. 调度号池渲染并捕获 1080P 高清 MP4 视频流。
3. 打印最终的视频直链、本地存储路径与预览链接。

## 修改网关与密钥配置

如果需要配置不同的中转站地址或自定义 API Key：
```bash
python "<插件根目录>/scripts/configure.py" "<网关URL，如 http://127.0.0.1:8765>" "<API密钥，如 sk-flow-xxxx>"
```
配置将持久化保存在用户家目录的 `~/.codex/google_flow_config.json`。
