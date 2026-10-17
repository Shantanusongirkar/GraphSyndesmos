import json
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api import app, graph  # existing FastAPI app + FalkorDB graph
from agent import (
    FUNCS,
    MODEL,
    SYSTEM,
    TOOLS,
    graph_from_rows,
)

import ollama


class AskRequest(BaseModel):
    question: str


@app.get("/stats")
def stats():
    """Node/edge counts and repo name for the top bar."""
    try:
        nodes = graph.query("MATCH (n) RETURN count(n)").result_set[0][0]
        edges = graph.query("MATCH ()-[e]->() RETURN count(e)").result_set[0][0]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Graph database unavailable") from exc
    return {"nodes": nodes, "edges": edges, "repo": "FalkorDB/FalkorDB"}


@app.post("/ask")
def ask(req: AskRequest):
    """Run the agent loop and return answer + per-step graph subgraphs + sources."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    steps = []
    answer = "Gave up after too many tool calls."

    try:
        for _ in range(5):  # safety limit on tool-call loops
            resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
            messages.append(resp.message)
            if not resp.message.tool_calls:
                answer = resp.message.content or ""
                break
            for call in resp.message.tool_calls:
                name, args = call.function.name, call.function.arguments
                if name not in FUNCS:
                    messages.append({"role": "tool", "tool_name": name,
                                     "content": "Unknown tool."})
                    continue
                try:
                    result = FUNCS[name](**args)
                except Exception as exc:
                    messages.append({"role": "tool", "tool_name": name,
                                     "content": f"Tool failed: {exc}"})
                    continue
                steps.append({
                    "tool": name,
                    "args": args,
                    "cypher": result["cypher"],
                    "rows": result["rows"],
                    "graph": result.get("graph", {"nodes": [], "edges": []}),
                })
                messages.append({"role": "tool", "tool_name": name,
                                 "content": json.dumps(result["rows"], default=str)})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent failed: {exc}") from exc

    # Sources derived from PR/Issue nodes in the graphs, not LLM text.
    sources = []
    seen_urls = set()
    for step in steps:
        for node in step["graph"]["nodes"]:
            url = node.get("url")
            if url and url.startswith("https://github.com/") and url not in seen_urls:
                seen_urls.add(url)
                label = f"{node['label']} #{node['number']}" if node.get("number") else node["name"]
                sources.append({"label": label, "url": url})

    return {"answer": answer, "steps": steps, "sources": sources}


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
