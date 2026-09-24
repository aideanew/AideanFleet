import subprocess
import sys
import time

proc = subprocess.Popen(
    [r".venv\Scripts\python.exe", "-u", "-m", "fleet.launcher.cli_start"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=0
)

# Read and print output until we see prompts, then send input
def read_until_prompt(proc, prompts):
    output = ""
    while True:
        char = proc.stdout.read(1)
        if not char:
            break
        output += char
        print(char, end='', flush=True)
        for prompt in prompts:
            if prompt in output:
                return output
    return output

prompts = [
    "项目名称",
    "项目路径", 
    "控制台端口",
    "启动模式"
]

inputs = [
    "Test09161119",
    r"E:\Demo\Test09161119",
    "5000",
    "run"
]

full_output = ""
for i, prompt in enumerate(prompts):
    out = read_until_prompt(proc, [prompt])
    full_output += out
    # Send input
    proc.stdin.write(inputs[i] + "\n")
    proc.stdin.flush()
    time.sleep(0.2)

# Read remaining output
remaining = proc.stdout.read()
if remaining:
    full_output += remaining
    print(remaining, end='')

proc.wait()
print("\n--- COMPLETE OUTPUT ---")
print(full_output)