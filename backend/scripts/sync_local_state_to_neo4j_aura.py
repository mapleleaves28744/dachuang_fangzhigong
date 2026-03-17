import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def load_simple_env():
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and not os.getenv(k):
            os.environ[k] = v


load_simple_env()

from database import get_user_knowledge  # noqa: E402
from db import get_session  # noqa: E402
from models import UserEvent, UserKnowledge, UserPlan, UserProfile  # noqa: E402
from neo4j_store import Neo4jGraphStore  # noqa: E402


def collect_local_user_ids():
    user_ids = set()
    with get_session() as session:
        for row in session.query(UserKnowledge.user_id).all():
            if row[0]:
                user_ids.add(row[0])
        for row in session.query(UserProfile.user_id).all():
            if row[0]:
                user_ids.add(row[0])
        for row in session.query(UserPlan.user_id).all():
            if row[0]:
                user_ids.add(row[0])
        for row in session.query(UserEvent.user_id).all():
            if row[0]:
                user_ids.add(row[0])
    return sorted(user_ids)


def normalize_knowledge(knowledge):
    if not isinstance(knowledge, dict):
        return {"concepts": [], "relations": [], "deleted_concepts": []}
    concepts = knowledge.get("concepts", [])
    relations = knowledge.get("relations", [])
    deleted = set(knowledge.get("deleted_concepts", []) or [])

    if not isinstance(concepts, list):
        concepts = []
    if not isinstance(relations, list):
        relations = []

    norm_concepts = []
    for item in concepts:
        if not isinstance(item, dict):
            continue
        c = (item.get("concept") or "").strip()
        if not c or c in deleted:
            continue
        norm_concepts.append(item)

    norm_relations = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        s = (rel.get("source") or "").strip()
        t = (rel.get("target") or "").strip()
        if not s or not t or s == t:
            continue
        if s in deleted or t in deleted:
            continue
        norm_relations.append(rel)

    return {
        "concepts": norm_concepts,
        "relations": norm_relations,
        "deleted_concepts": list(deleted),
    }


def get_remote_user_ids(store):
    with store.driver.session(database=store.database) as session:
        rows = session.run("MATCH (u:User) RETURN u.id AS id")
        return sorted({(r.get("id") or "").strip() for r in rows if (r.get("id") or "").strip()})


def get_remote_counts(store):
    with store.driver.session(database=store.database) as session:
        u = session.run("MATCH (u:User) RETURN count(u) AS c").single().get("c", 0)
        c = session.run("MATCH (n:Concept) RETURN count(n) AS c").single().get("c", 0)
        m = session.run("MATCH ()-[r:MASTERY]->() RETURN count(r) AS c").single().get("c", 0)
        rel = session.run("MATCH ()-[r:RELATED]->() RETURN count(r) AS c").single().get("c", 0)
    return {"users": int(u), "concepts": int(c), "mastery": int(m), "related": int(rel)}


def clear_user_remote_state(store, user_id):
    with store.driver.session(database=store.database) as session:
        session.run(
            """
            MATCH ()-[r:RELATED {user_id:$user_id}]->()
            DELETE r
            """,
            user_id=user_id,
        )
        session.run(
            """
            MATCH (u:User {id:$user_id})-[m:MASTERY]->(:Concept)
            DELETE m
            """,
            user_id=user_id,
        )
        session.run(
            """
            MATCH (u:User {id:$user_id})
            RETURN u
            """,
            user_id=user_id,
        )


def delete_remote_user(store, user_id):
    with store.driver.session(database=store.database) as session:
        session.run(
            """
            MATCH ()-[r:RELATED {user_id:$user_id}]->()
            DELETE r
            """,
            user_id=user_id,
        )
        session.run(
            """
            MATCH (u:User {id:$user_id})
            DETACH DELETE u
            """,
            user_id=user_id,
        )


def cleanup_orphan_concepts(store):
    with store.driver.session(database=store.database) as session:
        session.run(
            """
            MATCH (c:Concept)
            WHERE NOT (c)<-[:MASTERY]-(:User)
              AND NOT (c)-[:RELATED]-(:Concept)
            DELETE c
            """
        )


def main():
    store = Neo4jGraphStore()
    if not store.enabled:
        print("Neo4j is not enabled or not reachable. Abort.")
        return

    local_users = collect_local_user_ids()
    remote_users = get_remote_user_ids(store)

    before = get_remote_counts(store)
    print("[before]", before)
    print(f"local users: {len(local_users)} | remote users: {len(remote_users)}")

    local_set = set(local_users)
    remote_set = set(remote_users)

    removed_users = sorted(remote_set - local_set)
    for uid in removed_users:
        delete_remote_user(store, uid)

    synced_users = 0
    concept_total = 0
    relation_total = 0

    for uid in local_users:
        k = normalize_knowledge(get_user_knowledge(uid))
        clear_user_remote_state(store, uid)
        ok = store.upsert_user_graph(uid, k["concepts"], k["relations"])
        if ok:
            synced_users += 1
            concept_total += len(k["concepts"])
            relation_total += len(k["relations"])

    cleanup_orphan_concepts(store)

    after = get_remote_counts(store)
    print("[after]", after)
    print(
        {
            "synced_users": synced_users,
            "removed_remote_users": len(removed_users),
            "pushed_concepts": concept_total,
            "pushed_relations": relation_total,
        }
    )


if __name__ == "__main__":
    main()
