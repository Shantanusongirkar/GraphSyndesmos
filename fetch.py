import requests, json, os, time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TOKEN = os.environ["GH_TOKEN"]
REPO = "FalkorDB/FalkorDB"
OUT = "github_data.json"

s = requests.Session()
s.headers.update({"Authorization": f"Bearer {TOKEN}"})
retry = Retry(total=6, backoff_factor=1.5,
              status_forcelist=[429, 500, 502, 503, 504],
              allowed_methods=["GET"])
s.mount("https://", HTTPAdapter(max_retries=retry))

def pages(url, max_pages=5):
    out = []
    for p in range(1, max_pages + 1):
        r = s.get(url, params={"per_page": 100, "page": p, "state": "all"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        out += data
    return out

base = f"https://api.github.com/repos/{REPO}"

# resume from earlier progress if the file exists
data = json.load(open(OUT)) if os.path.exists(OUT) else {}

for key in ["contributors", "issues", "pulls"]:
    if key not in data:
        data[key] = pages(f"{base}/{key}")
        json.dump(data, open(OUT, "w"))
        print("fetched", key, len(data[key]))

data.setdefault("pr_files", {})
for pr in data["pulls"][:100]:
    n = str(pr["number"])
    if n in data["pr_files"]:
        continue
    try:
        data["pr_files"][n] = pages(f"{base}/pulls/{n}/files", max_pages=1)
    except Exception as e:
        print("skipping PR", n, "-", type(e).__name__)
        continue
    json.dump(data, open(OUT, "w"))
    print("PR files:", len(data["pr_files"]), end="\r")

print("\nsaved", {k: len(v) for k, v in data.items()})