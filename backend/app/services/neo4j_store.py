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
        self._raw_use_neo4j = os.getenv("USE_NEO4J", "auto").strip().lower()

        self.uri = os.getenv("NEO4J_URI", "")
        self.user = os.getenv("NEO4J_USER", "") or os.getenv("NEO4J_USERNAME", "")
        self.password = os.getenv("NEO4J_PASSWORD", "")
        self.database = os.getenv("NEO4J_DATABASE", "") or None

        if self._raw_use_neo4j in {"false", "0", "off", "no"}:
            self.use_neo4j = False
        elif self._raw_use_neo4j in {"true", "1", "on", "yes"}:
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
            self.last_error = self._diagnose_config_issue()
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

    def _diagnose_config_issue(self):
        if self._raw_use_neo4j in {"false", "0", "off", "no"}:
            return "neo4j disabled by USE_NEO4J"
        if not self.uri or not self.user or not self.password:
            return "missing NEO4J_URI/NEO4J_USER(NEO4J_USERNAME)/NEO4J_PASSWORD"
        return "neo4j is not enabled"

    def get_health_report(self, force=False):
        connected = self.ensure_connected(force=force)
        missing = []
        if not self.uri:
            missing.append("NEO4J_URI")
        if not self.user:
            missing.append("NEO4J_USER or NEO4J_USERNAME")
        if not self.password:
            missing.append("NEO4J_PASSWORD")

        return {
            "use_neo4j": bool(self.use_neo4j),
            "enabled": bool(self.enabled),
            "connected": bool(connected and self.enabled),
            "database": self.database or "neo4j",
            "retry_interval_seconds": float(self.retry_interval_seconds),
            "env": {
                "USE_NEO4J": self._raw_use_neo4j or "auto",
                "NEO4J_URI": bool(self.uri),
                "NEO4J_USER": bool(self.user),
                "NEO4J_PASSWORD": bool(self.password),
                "NEO4J_DATABASE": bool(self.database),
            },
            "missing": missing,
            "last_error": str(self.last_error or ""),
        }

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

    def query_related_concepts(self, concept, limit=8):
        """查询指定知识点的关联关系，供智能体工具安全复用。"""
        if not self.ensure_connected():
            return []

        concept = (concept or "").strip()
        if not concept:
            return []

        safe_limit = max(1, min(int(limit or 8), 20))

        try:
            with self.driver.session(database=self.database) as session:
                rows = session.run(
                    """
                    MATCH (n:Concept)
                    WHERE toLower(n.name) = toLower($concept)
                    OPTIONAL MATCH (n)-[r1:RELATED]->(m1:Concept)
                    OPTIONAL MATCH (m2:Concept)-[r2:RELATED]->(n)
                    WITH n,
                         collect({target: m1.name, rel_type: type(r1), rel_label: coalesce(r1.type, '相关')}) +
                         collect({target: m2.name, rel_type: type(r2), rel_label: coalesce(r2.type, '相关')}) AS rels
                    UNWIND rels AS rel
                    WITH rel
                    WHERE rel.target IS NOT NULL
                          RETURN rel.rel_type AS rel_type,
                              coalesce(rel.rel_label, '相关') AS rel_label,
                              rel.target AS target
                    LIMIT $limit
                    """,
                    concept=concept,
                    limit=safe_limit,
                )

                result = []
                for row in rows:
                    result.append(
                        {
                            "source": concept,
                            "target": row.get("target"),
                            "relation": row.get("rel_label") or row.get("rel_type") or "相关",
                        }
                    )

                return result
        except Exception as exc:
            self._handle_runtime_error(exc)
            return []

    def upsert_kb_note_graph(self, user_id, note_id, title, content, concepts, source="agent_kb", tags=None):
        """将知识库笔记同步为图谱节点，并建立笔记与概念关联。"""
        if not self.ensure_connected():
            return False

        uid = (user_id or "").strip()
        nid = (note_id or "").strip()
        if not uid or not nid:
            return False

        title = (title or "").strip() or "知识笔记"
        content = (content or "").strip()
        source = (source or "agent_kb").strip() or "agent_kb"
        tags = [str(x).strip() for x in (tags or []) if str(x).strip()]
        concepts = [str(x).strip() for x in (concepts or []) if str(x).strip()]
        now = datetime.now().isoformat()

        try:
            with self.driver.session(database=self.database) as session:
                session.run(
                    """
                    MERGE (u:User {id:$user_id})
                    MERGE (d:Document {id:$doc_id})
                    SET d.title=$title,
                        d.content=$content,
                        d.source=$source,
                        d.tags=$tags,
                        d.updated_at=$now
                    MERGE (u)-[r:OWNS_DOC]->(d)
                    SET r.updated_at=$now
                    """,
                    user_id=uid,
                    doc_id=nid,
                    title=title,
                    content=content,
                    source=source,
                    tags=tags,
                    now=now,
                )

                for concept in concepts:
                    session.run(
                        """
                        MERGE (c:Concept {name:$concept})
                        MERGE (d:Document {id:$doc_id})
                        MERGE (d)-[r:MENTIONS]->(c)
                        SET r.updated_at=$now
                        """,
                        concept=concept,
                        doc_id=nid,
                        now=now,
                    )
            return True
        except Exception as exc:
            self._handle_runtime_error(exc)
            return False

    def query_graph_rag_context(self, user_id, concepts, limit=8):
        """按概念返回文档-概念-概念关系，供 RAG-Graph 组合检索。P0 改造：增加对齐字段。"""
        if not self.ensure_connected():
            return []

        uid = (user_id or "").strip()
        concepts = [str(x).strip() for x in (concepts or []) if str(x).strip()]
        if not uid or not concepts:
            return []

        safe_limit = max(1, min(int(limit or 8), 30))
        try:
            with self.driver.session(database=self.database) as session:
                rows = session.run(
                    """
                    UNWIND $concepts AS c_name
                    MATCH (c:Concept)
                    WHERE toLower(c.name) = toLower(c_name)
                    OPTIONAL MATCH (d:Document)<-[:OWNS_DOC]-(:User {id:$user_id})
                                   WHERE (d)-[:MENTIONS]->(c)
                    OPTIONAL MATCH (c)-[r_out:RELATED]->(n_out:Concept)
                    OPTIONAL MATCH (n_in:Concept)-[r_in:RELATED]->(c)
                    WITH c, d,
                         collect({neighbor: n_out.name, relation: coalesce(r_out.type, '相关')}) +
                         collect({neighbor: n_in.name, relation: coalesce(r_in.type, '相关')}) AS rels
                    UNWIND rels AS rel
                    RETURN c.name AS concept,
                           d.id AS doc_id,
                           d.title AS doc_title,
                           rel.neighbor AS neighbor,
                           coalesce(rel.relation, '相关') AS relation
                    LIMIT $limit
                    """,
                    concepts=concepts,
                    user_id=uid,
                    limit=safe_limit,
                )

                out = []
                for idx, row in enumerate(rows):
                    if not any([row.get("doc_id"), row.get("neighbor")]):
                        continue
                    
                    # P0 改造：添加对齐字段（similarity_to_query 和 source_doc_id）
                    # 相似度基于概念匹配度（[0, 1]，单个匹配算 0.7，多匹配补分）
                    concept = row.get("concept", "")
                    similarity_base = 0.7 if concept in concepts else 0.4
                    similarity_score = round(min(1.0, similarity_base + 0.1 * (1 / max(1, idx + 1))), 3)
                    
                    out.append(
                        {
                            "concept": concept,
                            "doc_id": row.get("doc_id"),
                            "doc_title": row.get("doc_title"),
                            "neighbor": row.get("neighbor"),
                            "relation": row.get("relation") or "相关",
                            "similarity_to_query": similarity_score,  # P0 新增：与查询的相似度
                            "source_doc_id": "neo4j_" + str(row.get("doc_id") or idx),  # P0 新增：来源标识
                        }
                    )
                return out
        except Exception as exc:
            self._handle_runtime_error(exc)
            return []

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
                WHERE coalesce(m.mastery, 0.0) >= 0.7 AND s.name <> $target
                WITH t, collect(s) AS starts
                UNWIND starts AS start_node
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
                WHERE s.name <> t.name
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
