# Neo4j Quickstart

1. Open Neo4j Desktop.
2. Create a Local DBMS (password example: neo4j123456).
3. Start the DBMS and ensure Bolt is enabled on `localhost:7687`.
4. In PowerShell, set env vars before starting backend:

```powershell
$env:USE_NEO4J = "true"
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "neo4j123456"
```

5. Restart backend and check:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/health"
```

Expect `neo4j_enabled: true`.
