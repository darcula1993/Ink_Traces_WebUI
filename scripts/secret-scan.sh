#!/usr/bin/env bash
# 凭据扫描：默认扫描 git 暂存区新增行；也可扫描指定 diff。
# 用法：
#   scripts/secret-scan.sh                  扫描暂存区（git diff --cached）
#   scripts/secret-scan.sh --diff <文件|->  扫描 unified diff 文件（- 为标准输入）
#   scripts/secret-scan.sh --range <a..b>   扫描 git diff <a..b>
# 命中即退出码 1，只打印“文件:行号 规则名”，绝不打印命中内容。
# 放行：同一行含 test-key、private-test、configured-*-key、shared-*-key、*.invalid（如 example.invalid）或 secret-scan: allow 标记。
set -euo pipefail
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
case "${1:-}" in
  "")      git diff --cached -U0 --no-color --diff-filter=ACMR >"$tmp" ;;
  --diff)  [ -n "${2:-}" ] || { echo "usage: --diff <file|->" >&2; exit 2; }
           if [ "$2" = "-" ]; then cat >"$tmp"; else cat -- "$2" >"$tmp"; fi ;;
  --range) [ -n "${2:-}" ] || { echo "usage: --range <a..b>" >&2; exit 2; }
           git diff -U0 --no-color --diff-filter=ACMR "$2" >"$tmp" ;;
  *)       echo "usage: $0 [--diff <file|->|--range <a..b>]" >&2; exit 2 ;;
esac
python3 -I - "$tmp" <<'PY'
import re, sys
RULES = [
 ("private-key",   re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
 ("google-api-key",re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
 ("sk-key",        re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
 ("aws-key-id",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
 ("github-token",  re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
 ("bearer-token",  re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=\-]{16,}")),
 ("signed-url-param", re.compile(r"[?&;](?:X-Amz-Signature|X-Goog-Signature|X-Signature|Signature)=[^&\s\"']{8,}", re.I)),
 ("ark-endpoint-id", re.compile(r"\bep-[0-9]{8,}-[a-z0-9]+")),
 ("key-assignment", re.compile(r"""(?i)["']?[\w.-]*(?:api[_-]?key|secret|access[_-]?token|auth[_-]?token|password)["']?\s*[:=]\s*["'][A-Za-z0-9_\-+/=.]{16,}["']""")),
]
ALLOW = re.compile(r"test-key|private-test|(?:configured|shared)-[a-z]+-key|[A-Za-z0-9-]+\.invalid\b|secret-scan:\s*allow")
f = None; ln = 0; hits = []
for raw in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = raw.rstrip("\n")
    if line.startswith("+++ "):
        p = line[4:]; f = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p); continue
    m = re.match(r"@@ -\S+ \+(\d+)", line)
    if m: ln = int(m.group(1)); continue
    if line.startswith("+") and f:
        text = line[1:]
        if not ALLOW.search(text):
            for name, rx in RULES:
                if rx.search(text): hits.append((f, ln, name))
        ln += 1
for f_, l_, n_ in hits: print(f"{f_}:{l_}: {n_}")
if hits:
    print(f"secret-scan: {len(hits)} 处疑似凭据（内容未打印），请移除或改用占位后重试", file=sys.stderr); sys.exit(1)
print("secret-scan: OK")
PY
