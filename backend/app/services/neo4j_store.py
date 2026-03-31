import os
import time
from datetime import datetime

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable, SessionExpired
except Exception:
    GraphDatabase = None
    RETRYABLE_NEO4J_ERRORS = (OSError,)
else:
    RETRYABLE_NEO4J_ERRORS = (ServiceUnavailable, SessionExpired, OSError)


class Neo4jGraphStore:
    def __init__(self):
        self.enabled = False
        self.driver = None
        self.database = None
        self.last_error = ""
        self.use_neo4j = False
        self.uri = ""
        self.user = ""
        self.password = ""
        self.retry_interval_seconds = max(1.0, float(os.getenv("NEO4J_RETRY_INTERVAL_SECONDS", "5")))
        self._last_connect_attempt = 0.0

        raw_use_neo4j = os.getenv("USE_NEO4J", "auto").strip().lower()
        self.uri = os.getenv("NEO4J_URI", "")
        self.user = os.getenv("NEO4J_USER", "") or os.getenv("NEO4J_USERNAME", "")
        self.password = os.getenv("NEO4J_PASSWORD", "")
        self.database = os.getenv("NEO4J_DATABASE", "") or None

        if raw_use_neo4j in {"false", "0", "off", "no"}:
            self.use_neo4j = False
        elif raw_use_neo4j in {"true", "1", "on", "yes"}:
            self.use_neo4j = True
        else:
            # auto: credentials present means try enabling neo4j
            self.use_neo4j = bool(self.uri and self.user and self.password)

        self._connect(force=True)

    def _disconnect(self):
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
        self.driver = None

    def _connect(self, force=False):
        now = time.monotonic()
        if self.enabled and self.driver:
            return True

        if not force and (now - self._last_connect_attempt) < self.retry_interval_seconds:
            return False

        self._last_connect_attempt = now
        self.enabled = False
        self._disconnect()

        if not self.use_neo4j:
            self.last_error = ""
            return False
        if not GraphDatabase:
            self.last_error = "neo4j package is not installed"
            return False
        if not (self.uri and self.user and self.password):
            self.last_error = "missing NEO4J_URI/NEO4J_USER(NEO4J_USERNAME)/NEO4J_PASSWORD"
            return False

        try:
            driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            driver.verify_connectivity()
            self.driver = driver
            self.enabled = True
            self.last_error = ""
            return True
        except Exception as e:
            try:
                driver.close()
            except Exception:
                pass
            self.driver = None
            self.enabled = False
            self.last_error = f"{type(e).__name__}: {e}"
            return False

    def _handle_runtime_error(self, exc):
        self.last_error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, RETRYABLE_NEO4J_ERRORS):
            self.enabled = False
            self._disconnect()

    def ensure_connected(self, force=False):
        return self._connect(force=force)

    def close(self):
        self.enabled = False
        self._disconnect()

    def upsert_user_graph(self, user_id, concept_items, relations):
        if not self.ensure_connected():
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
        except Exception as exc:
            self._handle_runtime_error(exc)
            return False

    def update_mastery(self, user_id, concept, mastery, review_count=0, last_reviewed=None):
        if not self.ensure_connected():
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
        except Exception as exc:
            self._handle_runtime_error(exc)
            return False

    def delete_concept(self, user_id, concept):
        if not self.ensure_connected():
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
        except Exception as exc:
            self._handle_runtime_error(exc)
            return False

    def delete_user_graph(self, user_id):
        if not self.ensure_connected():
            return False

        user_id = (user_id or "").strip()
        if not user_id:
            return False

        try:
            with self.driver.session(database=self.database) as session:
                session.run(
                    """
                    MATCH (u:User {id:$user_id})-[m:MASTERY]->(:Concept)
                    DELETE m
                    """,
                    user_id=user_id,
                )

                session.run(
                    """
                    MATCH (:Concept)-[r:RELATED {user_id:$user_id}]->(:Concept)
                    DELETE r
                    """,
                    user_id=user_id,
                )

                session.run(
                    """
                    MATCH (u:User {id:$user_id})
                    DELETE u
                    """,
                    user_id=user_id,
                )

                session.run(
                    """
                    MATCH (c:Concept)
                    WHERE NOT (c)<-[:MASTERY]-(:User)
                      AND NOT (c)-[:RELATED]-()
                    DELETE c
                    """
                )
            return True
        except Exception as exc:
            self._handle_runtime_error(exc)
            return False

    def fetch_graph(self, user_id):
        if not self.ensure_connected():
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
        except Exception as exc:
            self._handle_runtime_error(exc)
            return None

    def concept_exists(self, concept):
        if not self.ensure_connected():
            return False

        concept = (concept or "").strip()
        if not concept:
            return False

        try:
            with self.driver.session(database=self.database) as session:
                row = session.run(
                    """
                    MATCH (c:Concept {name:$concept})
                    RETURN count(c) AS cnt
                    """,
                    concept=concept,
                ).single()
                return bool(row and int(row.get("cnt", 0)) > 0)
        except Exception as exc:
            self._handle_runtime_error(exc)
            return False

    def fetch_learning_path(self, user_id, target, max_depth=6):
        if not self.ensure_connected():
            return None

        target = (target or "").strip()
        if not target:
            return []

        depth = max(1, min(int(max_depth), 10))

        try:
            with self.driver.session(database=self.database) as session:
                # 优先从已掌握概念出发，若无则退化为任意可达路径。
                query = f"""
                MATCH (t:Concept {{name:$target}})
                OPTIONAL MATCH (u:User {{id:$user_id}})-[m:MASTERY]->(s:Concept)
                WHERE coalesce(m.mastery, 0.0) >= 0.7
                WITH t, collect(s) AS starts
                UNWIND CASE WHEN size(starts) = 0 THEN [null] ELSE starts END AS start_node
                MATCH p = shortestPath((start_node)-[:RELATED*..{depth}]->(t))
                RETURN [n IN nodes(p) | n.name] AS path
                ORDER BY length(p) ASC
                LIMIT 1
                """

                row = session.run(query, user_id=user_id, target=target).single()
                if row and row.get("path"):
                    return row.get("path")

                # 二次回退：从目标节点向前追溯前置链。
                fallback_query = f"""
                MATCH (t:Concept {{name:$target}})
                OPTIONAL MATCH p = shortestPath((s:Concept)-[:RELATED*..{depth}]->(t))
                RETURN [n IN nodes(p) | n.name] AS path
                ORDER BY length(p) ASC
                LIMIT 1
                """
                fallback_row = session.run(fallback_query, target=target).single()
                if fallback_row and fallback_row.get("path"):
                    return fallback_row.get("path")

                return []
        except Exception as exc:
            self._handle_runtime_error(exc)
            return None
