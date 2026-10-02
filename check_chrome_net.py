import subprocess

out = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'], encoding='gbk', errors='ignore')
for line in out.split('\n'):
    if ' 2792' in line:
        print(line.strip())
