import os
from datetime import datetime

try:
    from neo4j import GraphDatabase
except Exception:
    GraphDatabase = None


class Neo4jGraphStore:
    def __init__(self):
        self.enabled = False
        self.driver = None
        self.database = None
        self.last_error = ""

        raw_use_neo4j = os.getenv("USE_NEO4J", "auto").strip().lower()
        uri = os.getenv("NEO4J_URI", "")
        user = os.getenv("NEO4J_USER", "") or os.getenv("NEO4J_USERNAME", "")
        password = os.getenv("NEO4J_PASSWORD", "")
        self.database = os.getenv("NEO4J_DATABASE", "") or None

        if raw_use_neo4j in {"false", "0", "off", "no"}:
            use_neo4j = False
        elif raw_use_neo4j in {"true", "1", "on", "yes"}:
            use_neo4j = True
        else:
            # auto: credentials present means try enabling neo4j
            use_neo4j = bool(uri and user and password)

        if use_neo4j and GraphDatabase and uri and user and password:
            try:
                self.driver = GraphDatabase.driver(uri, auth=(user, password))
                self.driver.verify_connectivity()
                self.enabled = True
            except Exception as e:
                self.driver = None
                self.enabled = False
                self.last_error = f"{type(e).__name__}: {e}"
        elif use_neo4j and not GraphDatabase:
            self.last_error = "neo4j package is not installed"
        elif use_neo4j:
            self.last_error = "missing NEO4J_URI/NEO4J_USER(NEO4J_USERNAME)/NEO4J_PASSWORD"

    def close(self):
        if self.driver:
            self.driver.close()

    def upsert_user_graph(self, user_id, concept_items, relations):
        if not self.enabled or not self.driver:
            return False

        concept_items = concept_items or []
        relations = relations or []
        now = datetime.now().isoformat()

        try:
            with self.driver.session(database=self.database) as session:
                session.run("MERGE (u:User {id:$user_id})", user_id=user_id)

                for item in concept_items:
                    concept = (item.get("concept") or "").strip()
                    if not concept:
                        continue

                    mastery = float(item.get("mastery", 0.3))
                    review_count = int(item.get("review_count", 0))
                    last_reviewed = item.get("last_reviewed")

                    session.run(
                        """
                        MERGE (c:Concept {name:$concept})
                        ON CREATE SET c.created_at=$now
                        MERGE (u:User {id:$user_id})
                        MERGE (u)-[r:MASTERY]->(c)
                        SET r.mastery=$mastery,
                            r.review_count=$review_count,
                            r.last_reviewed=$last_reviewed,
                            r.updated_at=$now
                        """,
                        user_id=user_id,
                        concept=concept,
                        mastery=mastery,
                        review_count=review_count,
                        last_reviewed=last_reviewed,
                        now=now,
                    )

                for rel in relations:
                    source = (rel.get("source") or "").strip()
                    target = (rel.get("target") or "").strip()
                    rel_type = (rel.get("type") or "相关").strip()
                    if not source or not target:
                        continue

                    session.run(
                        """
                        MERGE (s:Concept {name:$source})
                        MERGE (t:Concept {name:$target})
                        MERGE (s)-[r:RELATED {user_id:$user_id, type:$rel_type}]->(t)
                        SET r.updated_at=$now
                        """,
                        user_id=user_id,
                        source=source,
                        target=target,
                        rel_type=rel_type,
                        now=now,
                    )
            return True
        except Exception:
            return False

    def update_mastery(self, user_id, concept, mastery, review_count=0, last_reviewed=None):
        if not self.enabled or not self.driver:
            return False

        now = datetime.now().isoformat()
        try:
            with self.driver.session(database=self.database) as session:
                session.run(
                    """
                    MERGE (u:User {id:$user_id})
                    MERGE (c:Concept {name:$concept})
                    MERGE (u)-[r:MASTERY]->(c)
                    SET r.mastery=$mastery,
                        r.review_count=$review_count,
                        r.last_reviewed=$last_reviewed,
                        r.updated_at=$now
                    """,
                    user_id=user_id,
                    concept=concept,
                    mastery=float(mastery),
                    review_count=int(review_count),
                    last_reviewed=last_reviewed,
                    now=now,
                )
            return True
        except Exception:
            return False

    def delete_concept(self, user_id, concept):
        if not self.enabled or not self.driver:
            return False

        concept = (concept or "").strip()
        if not concept:
            return False

        try:
            with self.driver.session(database=self.database) as session:
                session.run(
                    """
                    MATCH (u:User {id:$user_id})-[m:MASTERY]->(c:Concept {name:$concept})
                    DELETE m
                    """,
                    user_id=user_id,
                    concept=concept,
                )

                session.run(
                    """
                    MATCH (s:Concept)-[r:RELATED {user_id:$user_id}]->(t:Concept)
                    WHERE s.name = $concept OR t.name = $concept
                    DELETE r
                    """,
                    user_id=user_id,
                    concept=concept,
                )

                session.run(
                    """
                    MATCH (c:Concept {name:$concept})
                    WHERE NOT (c)<-[:MASTERY]-(:User)
                      AND NOT (c)-[:RELATED]-(:Concept)
                    DELETE c
                    """,
                    concept=concept,
                )
            return True
        except Exception:
            return False

    def fetch_graph(self, user_id):
        if not self.enabled or not self.driver:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                node_rows = session.run(
                    """
                    MATCH (u:User {id:$user_id})-[m:MASTERY]->(c:Concept)
                    RETURN c.name AS name,
                           coalesce(m.mastery, 0.2) AS mastery,
                           coalesce(m.review_count, 0) AS review_count
                    """,
                    user_id=user_id,
                )

                nodes = []
                for row in node_rows:
                    nodes.append(
                        {
                            "id": row["name"],
                            "name": row["name"],
                            "description": "",
                            "difficulty": 0.5,
                            "mastery": round(float(row["mastery"]), 3),
                            "confidence": 0.85,
                        }
                    )

                link_rows = session.run(
                    """
                    MATCH (s:Concept)-[r:RELATED {user_id:$user_id}]->(t:Concept)
                    RETURN s.name AS source, t.name AS target, r.type AS type
                    """,
                    user_id=user_id,
                )

                links = []
                for row in link_rows:
                    links.append(
                        {
                            "source": row["source"],
                            "target": row["target"],
                            "label": row["type"] or "相关",
                        }
                    )

                return {
                    "nodes": nodes,
                    "links": links,
                    "updated_at": datetime.now().isoformat(),
                }
        except Exception:
            return None
