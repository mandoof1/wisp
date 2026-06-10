#!/usr/bin/env python3
import subprocess, sys

r = subprocess.run(
    [sys.executable, "-m", "pip", "install", "uvicorn", "httptools"],
    capture_output=True, text=True, timeout=120
)
print("STDOUT:", r.stdout[-500:])
print("STDERR:", r.stderr[-500:])
print("RC:", r.returncode)
