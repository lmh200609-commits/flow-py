import subprocess
import json

ps = subprocess.check_output(['powershell', '-NoProfile', '-Command', 'Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json'], encoding='utf-8')
data = json.loads(ps)
for item in data:
    print(f"{item['ProcessName']} (PID {item['Id']}): {item['MainWindowTitle']}")
