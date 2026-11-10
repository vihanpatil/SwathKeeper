"""Select a spread of public DataFlash logs and fetch each into its own directory with a sha256.
Usage: fetch.py gh_candidates.json autotest_all.txt OUTDIR. Logs are untrusted data: only bytes are written."""
import hashlib, json, os, subprocess, sys, urllib.parse
cands, autotest, out = json.load(open(sys.argv[1])), open(sys.argv[2]).read().split(), sys.argv[3]
PER_REPO = {"erlerobot/logs": 4, "VinayMatade/TEAM_18_E": 3, "BeastAyyG/ardupilot-log-diagnosis": 3}
SKIP_REPO = {"nischay25/first-pr"}                      # same 77 files as BeastAyyG (a copy)
picks, seen_sizes = [], set()
by_repo = {}
for c in cands:
    by_repo.setdefault(c["repo"], []).append(c)
for repo, items in sorted(by_repo.items()):
    if repo in SKIP_REPO: continue
    items = sorted((i for i in items if i["size"] <= 25_000_000), key=lambda i: i["path"])
    k = PER_REPO.get(repo, 2)
    step = max(1, len(items) // k)
    for i in items[::step][:k]:
        if i["size"] in seen_sizes: continue             # the same bytes under another name
        seen_sizes.add(i["size"])
        url = f"https://raw.githubusercontent.com/{repo}/{i['sha']}/{urllib.parse.quote(i['path'])}"
        picks.append({"population": "github", "source": repo, "url": url, "pinned": True, "licence": i["licence"], "path": i["path"]})
cop = sorted(a for a in autotest if a.startswith("ArduCopter-DataFlash-"))
for a in cop[::max(1, len(cop) // 12)][:12] + [a for a in autotest if a.startswith("Rover-")]:
    picks.append({"population": "sitl-autotest", "source": "autotest.ardupilot.org", "url": "https://autotest.ardupilot.org/" + a,
                  "pinned": False, "licence": "GPL-3.0 (ArduPilot autotest output)", "path": a})
manifest = []
for n, p in enumerate(picks):
    d = os.path.join(out, f"{n:02d}"); os.makedirs(d, exist_ok=True); f = os.path.join(d, "log.bin")
    if not os.path.exists(f):
        r = subprocess.run(["curl", "-fsSL", "-m", "180", "--max-filesize", "60000000", "-o", f, p["url"]])
        if r.returncode != 0:
            print("FETCH FAILED", p["url"]); 
            if os.path.exists(f): os.remove(f)
            continue
    b = open(f, "rb").read()
    p.update(id=f"{n:02d}", size_bytes=len(b), sha256=hashlib.sha256(b).hexdigest(), dataflash_magic=b[:2] == b"\xa3\x95")
    manifest.append(p)
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
ok = [m for m in manifest if m["dataflash_magic"]]
print(len(manifest), "fetched;", len(ok), "are DataFlash;", round(sum(m["size_bytes"] for m in manifest) / 1e6, 1), "MB")
for m in manifest: print(f"  {m['id']} {'DF ' if m['dataflash_magic'] else 'NOT'} {m['size_bytes']:>9} {m['population']:<14} {m['source']}  {m['path'][:70]}")
