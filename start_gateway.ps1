$env:PYTHONUTF8=1
Set-Location -LiteralPath "D:\chatgpt聊天记录1\日常\flow-py"
Write-Host "[Starting Google Flow (Veo 3.1) Local Gateway on http://127.0.0.1:8765]..." -ForegroundColor Cyan
py -3.11 gateway.py
