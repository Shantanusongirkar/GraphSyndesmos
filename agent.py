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


def run(cypher, params=None):
    rows = graph.ro_query(cypher, params or {}).result_set
    return {"cypher": cypher.strip(), "params": params or {}, "rows": rows}


def top_contributors(limit: int = 5):
    """Find the people who authored the most pull requests.

    Args:
        limit: how many people to return
    """
    return run(
        "MATCH (p:Person)-[:AUTHORED]->(r:PR) "
        "RETURN p.login AS person, count(r) AS prs ORDER BY prs DESC LIMIT $n",
        {"n": int(limit)},
    )


def hot_files(limit: int = 10):
    """Find the files that change most often across pull requests.

    Args:
        limit: how many files to return
    """
    return run(
        "MATCH (:PR)-[:TOUCHES]->(f:File) "
        "RETURN f.path AS file, count(*) AS changes ORDER BY changes DESC LIMIT $n",
        {"n": int(limit)},
    )


def module_insights(name: str):
    """Find files whose path contains a word, with their pull requests and contributors.

    Args:
        name: part of a file path, for example 'graph' or 'src/index'
    """
    return run(
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


def who_knows_module(name: str):
    """Rank people by how many pull requests they authored touching files that match a word.

    Args:
        name: part of a file path, for example 'graph' or 'src/index'
    """
    return run(
        """
        MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(f:File)
        WHERE toLower(f.path) CONTAINS toLower($module)
        RETURN p.login AS person, count(DISTINCT pr) AS prs
        ORDER BY prs DESC LIMIT 5
        """,
        {"module": name},
    )


def prs_by_person(login: str):
    """List the most recent pull requests written by one person.

    Args:
        login: the person's GitHub login
    """
    return run(
        "MATCH (:Person {login:$l})-[:AUTHORED]->(r:PR) "
        "RETURN r.number AS number, r.title AS title, r.state AS state "
        "ORDER BY r.number DESC LIMIT 10",
        {"l": login},
    )


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