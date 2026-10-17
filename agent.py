"""Repo graph agent: a local LLM (Ollama) picks graph tools, FalkorDB answers.

Run:  python agent.py
Needs: FalkorDB running, `repo` graph loaded (load.py), Ollama running with the model pulled.
"""
import json
import os

import ollama
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
graph = FalkorDB(
    host=os.getenv("FALKORDB_HOST", "localhost"),
    port=int(os.getenv("FALKORDB_PORT", "6379")),
).select_graph("repo")


REPO = "FalkorDB/FalkorDB"


def _node_obj(n):
    """Convert a falkordb Node into a plain graph node dict."""
    props = n.properties or {}
    labels = n.labels or []
    label = labels[0] if labels else "Node"
    name = props.get("login") or props.get("path") or props.get("title") or str(props)
    node = {
        "id": str(n.id),
        "label": label,
        "name": name,
    }
    if props.get("number") is not None:
        node["number"] = int(props["number"])
    if label == "PR":
        node["url"] = f"https://github.com/{REPO}/pull/{node.get('number')}"
    elif label == "Issue":
        node["url"] = f"https://github.com/{REPO}/issues/{node.get('number')}"
    return node


def _edge_obj(e):
    """Convert a falkordb Edge into a plain graph edge dict."""
    return {
        "source": str(e.src_node),
        "target": str(e.dest_node),
        "type": e.relation,
    }


def graph_from_rows(rows):
    """Build {"nodes": [...], "edges": [...]} from falkordb result rows."""
    nodes = {}
    edges = []
    seen_edges = set()
    for row in rows:
        for item in row:
            if hasattr(item, "labels") and not hasattr(item, "relation"):
                nid = str(item.id)
                if nid not in nodes:
                    nodes[nid] = _node_obj(item)
            elif hasattr(item, "relation"):
                key = (str(item.src_node), str(item.dest_node), item.relation)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(_edge_obj(item))
    return {"nodes": list(nodes.values()), "edges": edges}


def run(cypher, params=None):
    rows = graph.ro_query(cypher, params or {}).result_set
    return {"cypher": cypher.strip(), "params": params or {}, "rows": rows}


def top_contributors(limit: int = 5):
    """Find the people who authored the most pull requests.

    Args:
        limit: how many people to return
    """
    result = run(
        "MATCH (p:Person)-[:AUTHORED]->(r:PR) "
        "RETURN p.login AS person, count(r) AS prs ORDER BY prs DESC LIMIT $n",
        {"n": int(limit)},
    )
    top_logins = [row[0] for row in result["rows"]]
    gres = graph.ro_query(
        "MATCH (p:Person)-[a:AUTHORED]->(r:PR) "
        "WHERE p.login IN $logins "
        "RETURN p, a, r",
        {"logins": top_logins},
    )
    result["graph"] = graph_from_rows(gres.result_set)
    return result


def hot_files(limit: int = 10):
    """Find the files that change most often across pull requests.

    Args:
        limit: how many files to return
    """
    result = run(
        "MATCH (:PR)-[:TOUCHES]->(f:File) "
        "RETURN f.path AS file, count(*) AS changes ORDER BY changes DESC LIMIT $n",
        {"n": int(limit)},
    )
    top_paths = [row[0] for row in result["rows"]]
    gres = graph.ro_query(
        "MATCH (r:PR)-[t:TOUCHES]->(f:File) "
        "WHERE f.path IN $paths "
        "RETURN r, t, f",
        {"paths": top_paths},
    )
    result["graph"] = graph_from_rows(gres.result_set)
    return result


def module_insights(name: str):
    """Find files whose path contains a word, with their pull requests and contributors.

    Args:
        name: part of a file path, for example 'graph' or 'src/index'
    """
    result = run(
        """
        MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(f:File)
        WHERE toLower(f.path) CONTAINS toLower($module)
        RETURN f.path AS file,
               count(DISTINCT pr) AS pull_requests,
               collect(DISTINCT p.login)[0..5] AS contributors,
               collect(DISTINCT pr.title)[0..3] AS example_pr_titles
        ORDER BY pull_requests DESC LIMIT 10
        """,
        {"module": name},
    )
    gres = graph.ro_query(
        """
        MATCH (p:Person)-[a:AUTHORED]->(pr:PR)-[t:TOUCHES]->(f:File)
        WHERE toLower(f.path) CONTAINS toLower($module)
        RETURN p, a, pr, t, f
        """,
        {"module": name},
    )
    result["graph"] = graph_from_rows(gres.result_set)
    return result


def who_knows_module(name: str):
    """Rank people by how many pull requests they authored touching files that match a word.

    Args:
        name: part of a file path, for example 'graph' or 'src/index'
    """
    result = run(
        """
        MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(f:File)
        WHERE toLower(f.path) CONTAINS toLower($module)
        RETURN p.login AS person, count(DISTINCT pr) AS prs
        ORDER BY prs DESC LIMIT 5
        """,
        {"module": name},
    )
    gres = graph.ro_query(
        """
        MATCH (p:Person)-[a:AUTHORED]->(pr:PR)-[t:TOUCHES]->(f:File)
        WHERE toLower(f.path) CONTAINS toLower($module)
        RETURN p, a, pr, t, f
        """,
        {"module": name},
    )
    result["graph"] = graph_from_rows(gres.result_set)
    return result


def prs_by_person(login: str):
    """List the most recent pull requests written by one person.

    Args:
        login: the person's GitHub login
    """
    result = run(
        "MATCH (:Person {login:$l})-[:AUTHORED]->(r:PR) "
        "RETURN r.number AS number, r.title AS title, r.state AS state "
        "ORDER BY r.number DESC LIMIT 10",
        {"l": login},
    )
    gres = graph.ro_query(
        "MATCH (p:Person {login:$l})-[a:AUTHORED]->(r:PR) "
        "RETURN p, a, r",
        {"l": login},
    )
    result["graph"] = graph_from_rows(gres.result_set)
    return result


TOOLS = [top_contributors, hot_files, module_insights, who_knows_module, prs_by_person]
FUNCS = {f.__name__: f for f in TOOLS}

SYSTEM = (
    "You answer questions about a GitHub repository using tools that query a graph. "
    "Always call a tool for repo facts. Never invent names, files or numbers. "
    "If a tool returns no rows, say you found nothing. Keep answers short."
)


def ask(question):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    for _ in range(5):  # safety limit on tool-call loops
        resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
        messages.append(resp.message)
        if not resp.message.tool_calls:
            return resp.message.content
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
            # This printout is the "show the path behind the answer" part.
            print(f"\n[graph query] {name}({args})\n{result['cypher']}\n")
            messages.append({"role": "tool", "tool_name": name,
                             "content": json.dumps(result["rows"], default=str)})
    return "Gave up after too many tool calls."


if __name__ == "__main__":
    print(f"GraphSyndesmos agent ({MODEL}). Empty line to quit.")
    while True:
        q = input("\nAsk: ").strip()
        if not q or q.lower() in ("quit", "exit"):
            break
        print("\nAnswer:", ask(q))