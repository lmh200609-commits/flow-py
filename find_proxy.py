import subprocess

out = subprocess.check_output(['tasklist', '/fo', 'csv', '/nh'], encoding='gbk', errors='ignore')
lines = out.strip().split('\n')
names = set()
for line in lines:
    parts = line.split(',')
    if len(parts) > 0:
        names.add(parts[0].replace('"', '').strip())

keywords = ['clash', 'v2ray', 'xray', 'sing', 'neko', 'shadow', 'vpn', 'proxy', 'edge', 'chrome', 'watt', 'steam', 'agent', 'tailscale', 'zerotier']
matched = [n for n in names if any(k in n.lower() for k in keywords)]
print("Matched proxy-related processes:", matched)
