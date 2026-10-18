"""Pre-publication check: this repository contains astronomy only.

Fails if any tracked text file contains CJK characters or words that point to
interpretive material (course handouts, rule ids, scores).
"""
import re
import subprocess
import sys

BANNED = re.compile(r"[　-〿㐀-鿿＀-￯]|\bSATA\b|handout|lesson|rule_id|dignit|interpret", re.I)
ALLOW = {"LICENSE", "scripts/content_check.py"}

files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
bad = []
for f in files:
    if f in ALLOW or f.endswith((".png", ".jpg")):
        continue
    for i, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
        if BANNED.search(line):
            bad.append(f"{f}:{i}: {line.strip()[:100]}")
print("\n".join(bad) or "content check passed")
sys.exit(1 if bad else 0)
