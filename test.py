from falkordb import FalkorDB

db = FalkorDB(host="localhost", port=6379)
g = db.select_graph("test")

g.query("CREATE (:Person {name:'Alice'})-[:KNOWS]->(:Person {name:'Bob'})")
result = g.query("MATCH (a)-[:KNOWS]->(b) RETURN a.name, b.name")
print(result.result_set)