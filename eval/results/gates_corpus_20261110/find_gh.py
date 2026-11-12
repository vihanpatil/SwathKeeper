"""List DataFlash-sized .bin blobs in candidate public repos (read-only GitHub API through `gh`)."""
import json, re, subprocess, sys
SKIP = re.compile(r"(?i)(firmware|bootloader|font|\.apj|node_modules|/build/|eeprom|rom\.bin|esp|stm32|\.git/)")
def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
out = []
for spec in open(sys.argv[1]).read().split():
    repo = gh(f"repos/{spec}")
    if not repo: continue
    head = gh(f"repos/{spec}/commits/{repo['default_branch']}")
    if not head: continue
    tree = gh(f"repos/{spec}/git/trees/{head['sha']}?recursive=1")
    if not tree: continue
    for b in tree.get("tree", []):
        if b["type"] == "blob" and re.search(r"\.(bin|BIN)$", b["path"]) and 150_000 < b.get("size", 0) < 60_000_000 and not SKIP.search(b["path"]):
            out.append({"repo": spec, "sha": head["sha"], "size": b["size"], "path": b["path"],
                        "licence": (repo.get("license") or {}).get("spdx_id")})
json.dump(out, open(sys.argv[2], "w"), indent=1)
from collections import Counter
c = Counter(o["repo"] for o in out)
print(len(out), "candidates in", len(c), "repos")
for r, n in c.most_common(40): print(f"  {n:4d}  {r}")
