import json, re
from falkordb import FalkorDB

data = json.load(open("github_data.json"))
db = FalkorDB(host="localhost", port=6379)
g = db.select_graph("repo")

# start fresh each run so re-running never duplicates
try:
    g.delete()
except Exception:
    pass
g = db.select_graph("repo")

# People who contributed
for c in data["contributors"]:
    g.query(
        "MERGE (p:Person {login:$l}) SET p.commits=$n",
        {"l": c["login"], "n": c["contributions"]},
    )

# Issues (the issues endpoint also returns PRs, so skip those)
for i in data["issues"]:
    if "pull_request" in i:
        continue
    g.query(
        """MERGE (p:Person {login:$l})
           MERGE (i:Issue {number:$n})
           SET i.title=$t, i.state=$s
           MERGE (p)-[:AUTHORED]->(i)""",
        {"l": i["user"]["login"], "n": i["number"], "t": i["title"], "s": i["state"]},
    )

# Pull requests, the files they touch, and the issues they fix
for pr in data["pulls"]:
    g.query(
        """MERGE (p:Person {login:$l})
           MERGE (r:PR {number:$n})
           SET r.title=$t, r.state=$s
           MERGE (p)-[:AUTHORED]->(r)""",
        {"l": pr["user"]["login"], "n": pr["number"], "t": pr["title"], "s": pr["state"]},
    )
    for f in data["pr_files"].get(str(pr["number"]), []):
        g.query(
            """MATCH (r:PR {number:$n})
               MERGE (f:File {path:$path})
               MERGE (r)-[:TOUCHES]->(f)""",
            {"n": pr["number"], "path": f["filename"]},
        )
    # links like "fixes #123" in the PR description
    for num in re.findall(r"(?:fix(?:es)?|close[sd]?|resolve[sd]?)\s+#(\d+)",
                          pr.get("body") or "", flags=re.I):
        g.query(
            """MATCH (r:PR {number:$n})
               MERGE (i:Issue {number:$i})
               MERGE (r)-[:FIXES]->(i)""",
            {"n": pr["number"], "i": int(num)},
        )

print(g.query("MATCH (n) RETURN count(n)").result_set, "nodes")
print(g.query("MATCH ()-[e]->() RETURN count(e)").result_set, "edges")