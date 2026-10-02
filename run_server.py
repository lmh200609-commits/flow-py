import subprocess
import sys
import time
from pathlib import Path

base_dir = Path("D:/chatgpt聊天记录1/日常/flow-py")
cmd = [sys.executable, str(base_dir / "gateway.py")]

p = subprocess.Popen(
    cmd,
    cwd=str(base_dir),
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)

pid_file = base_dir / "server.pid"
pid_file.write_text(str(p.pid))
print(f"Server started with PID: {p.pid}")
