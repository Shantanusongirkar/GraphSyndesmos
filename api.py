
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from falkordb import FalkorDB

load_dotenv()

app = FastAPI(title="GraphSyndesmos API")

db = FalkorDB(
    host=os.getenv("FALKORDB_HOST", "localhost"),
    port=int(os.getenv("FALKORDB_PORT", "6379")),
)

graph = db.select_graph("repo")


@app.get("/health")
def health():
    try:
        result = graph.query("MATCH (n) RETURN count(n)")
        return {"status": "ok", "graph_nodes": result.result_set[0][0]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Graph database unavailable") from exc


@app.get("/api/module")
def module_insights(name: str = Query(min_length=1, max_length=200)):
    query = """
    MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(f:File)
    WHERE toLower(f.path) CONTAINS toLower($module)
    RETURN
        f.path AS file,
        count(DISTINCT pr) AS pull_requests,
        collect(DISTINCT p.login)[0..5] AS contributors,
        collect(DISTINCT {
            number: pr.number,
            title: pr.title
        })[0..5] AS pull_request_details
    ORDER BY pull_requests DESC
    LIMIT 10
"""

    try:
        result = graph.ro_query(query, {"module": name})
        rows = result.result_set

        return {
            "module": name,
            "results": [
                {
                    "file": row[0],
                    "pull_requests": row[1],
                    "contributors": row[2],
                    "pull_request_details": row[3],
                }
                for row in rows
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not query repository graph") from exc
