@echo off
title Google Flow Video Gateway
set PYTHONUTF8=1
cd /d "D:\chatgpt聊天记录1\日常\flow-py"
echo [Starting Google Flow (Veo 3.1) Local Gateway on port 8765...]
py -3.11 gateway.py
pause
