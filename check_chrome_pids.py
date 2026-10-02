import subprocess

out = subprocess.check_output(['powershell', '-NoProfile', '-Command', '(Get-Process chrome).Id'], encoding='utf-8')
pids = [p.strip() for p in out.strip().split('\n') if p.strip()]

net_out = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'], encoding='gbk', errors='ignore')
external_conns = []
for line in net_out.split('\n'):
    parts = line.split()
    if len(parts) >= 5 and parts[-1] in pids:
        remote = parts[2]
        if not remote.startswith('127.0.0.1') and not remote.startswith('[::1]'):
            external_conns.append(f"{parts[1]} -> {remote} ({parts[3]}) PID:{parts[-1]}")

print("Total external connections from Chrome:", len(external_conns))
for c in external_conns[:15]:
    print(" ", c)
