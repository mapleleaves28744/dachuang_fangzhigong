import copy
import unittest
from unittest.mock import patch

try:
    from app import server as backend_app
    _APP_IMPORT_ERROR = ""
except Exception as e:
    backend_app = None
    _APP_IMPORT_ERROR = str(e)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestAuthContract(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()
        self.users = {}
        self.sessions = {}
        self.plan_store = {}
        self.knowledge_store = {}
        self.profile_store = {}
        self.event_store = {}
        self.space_store = {}

    def _patch_auth_storage(self):
        def get_auth_user(username):
            item = self.users.get(username)
            return copy.deepcopy(item) if item else None

        def upsert_auth_user(user):
            payload = copy.deepcopy(user)
            self.users[payload["username"]] = payload
            return copy.deepcopy(payload)

        def get_auth_session_by_token_hash(token_hash):
            item = self.sessions.get(token_hash)
            return copy.deepcopy(item) if item else None

        def upsert_auth_session(session_data):
            payload = copy.deepcopy(session_data)
            self.sessions[payload["token_hash"]] = payload
            return copy.deepcopy(payload)

        def revoke_auth_session(token_hash, revoked_at):
            item = self.sessions.get(token_hash)
            if not item:
                return False
            item["revoked_at"] = revoked_at
            return True

        def touch_auth_session(token_hash, last_seen_at):
            item = self.sessions.get(token_hash)
            if not item:
                return False
            item["last_seen_at"] = last_seen_at
            return True

        def append_user_event(user_id, suffix, item):
            key = (user_id, suffix)
            event_list = self.event_store.get(key, [])
            event_list.append(copy.deepcopy(item))
            self.event_store[key] = event_list

        def delete_auth_user_account(username):
            payload = {
                "user_id": username,
                "auth_user_deleted": False,
                "sessions_deleted": 0,
                "plans_deleted": 0,
                "knowledge_deleted": 0,
                "profile_deleted": 0,
                "events_deleted": 0,
                "spaces_deleted": 0,
                "space_items_deleted": 0,
            }

            if self.users.pop(username, None):
                payload["auth_user_deleted"] = True

            for token_hash in list(self.sessions.keys()):
                if self.sessions[token_hash].get("username") != username:
                    continue
                del self.sessions[token_hash]
                payload["sessions_deleted"] += 1

            if self.plan_store.pop(username, None) is not None:
                payload["plans_deleted"] = 1
            if self.knowledge_store.pop(username, None) is not None:
                payload["knowledge_deleted"] = 1
            if self.profile_store.pop(username, None) is not None:
                payload["profile_deleted"] = 1

            for key in list(self.event_store.keys()):
                if key[0] != username:
                    continue
                del self.event_store[key]
                payload["events_deleted"] += 1

            space_payload = self.space_store.pop(username, None) or {"spaces": []}
            payload["spaces_deleted"] = len(space_payload.get("spaces", [])) if isinstance(space_payload, dict) else 0
            if isinstance(space_payload, dict):
                payload["space_items_deleted"] = sum(
                    len(space.get("items", []))
                    for space in (space_payload.get("spaces", []) if isinstance(space_payload.get("spaces"), list) else [])
                    if isinstance(space, dict)
                )

            return payload

        return patch.multiple(
            backend_app,
            delete_auth_user_account=delete_auth_user_account,
            get_auth_user=get_auth_user,
            upsert_auth_user=upsert_auth_user,
            get_auth_session_by_token_hash=get_auth_session_by_token_hash,
            upsert_auth_session=upsert_auth_session,
            revoke_auth_session=revoke_auth_session,
            touch_auth_session=touch_auth_session,
            append_user_event=append_user_event,
        )

    def _patch_plan_storage(self):
        def get_user_plans(user_id):
            item = self.plan_store.get(user_id, [])
            return copy.deepcopy(item)

        def set_user_plans(user_id, plans):
            self.plan_store[user_id] = copy.deepcopy(plans)

        return patch.multiple(
            backend_app,
            get_user_plans=get_user_plans,
            set_user_plans=set_user_plans,
        )

    def _patch_learning_state_storage(self):
        def get_user_knowledge(user_id):
            item = self.knowledge_store.get(user_id, {"concepts": [], "relations": [], "deleted_concepts": []})
            return copy.deepcopy(item)

        def set_user_knowledge(user_id, knowledge):
            self.knowledge_store[user_id] = copy.deepcopy(knowledge)

        def get_user_profile(user_id):
            item = self.profile_store.get(user_id, {})
            return copy.deepcopy(item)

        def set_user_profile(user_id, profile):
            self.profile_store[user_id] = copy.deepcopy(profile)

        def load_user_event_list(user_id, suffix):
            item = self.event_store.get((user_id, suffix), [])
            return copy.deepcopy(item)

        def save_user_event_list(user_id, suffix, event_list):
            self.event_store[(user_id, suffix)] = copy.deepcopy(event_list)

        def build_learning_profile(user_id):
            profile = {
                "user_id": user_id,
                "updated_at": "2026-03-30T12:00:00",
            }
            self.profile_store[user_id] = copy.deepcopy(profile)
            return profile

        def get_user_space_payload(user_id):
            item = self.space_store.get(user_id, {"activeEntrySpaceId": "", "spaces": []})
            return copy.deepcopy(item)

        def set_user_space_payload(user_id, payload):
            self.space_store[user_id] = copy.deepcopy(payload)

        return patch.multiple(
            backend_app,
            get_user_knowledge=get_user_knowledge,
            set_user_knowledge=set_user_knowledge,
            get_user_profile=get_user_profile,
            set_user_profile=set_user_profile,
            get_user_space_payload=get_user_space_payload,
            set_user_space_payload=set_user_space_payload,
            load_user_event_list=load_user_event_list,
            save_user_event_list=save_user_event_list,
            build_learning_profile=build_learning_profile,
        )

    def test_register_me_logout_contract(self):
        with self._patch_auth_storage():
            register_resp = self.client.post("/api/auth/register", json={
                "username": "student_001",
                "password": "secret123",
                "display_name": "小杭",
                "locale": "CN",
            })

            self.assertEqual(register_resp.status_code, 200)
            register_data = register_resp.get_json()
            self.assertTrue(register_data.get("success"))
            auth = register_data.get("auth", {})
            self.assertTrue(auth.get("token"))
            self.assertEqual(auth.get("user", {}).get("username"), "student_001")
            self.assertEqual(auth.get("user", {}).get("display_name"), "小杭")

            token = auth.get("token")
            headers = {"Authorization": f"Bearer {token}"}

            me_resp = self.client.get("/api/auth/me", headers=headers)
            self.assertEqual(me_resp.status_code, 200)
            me_data = me_resp.get_json()
            self.assertTrue(me_data.get("success"))
            self.assertEqual(me_data.get("auth", {}).get("user", {}).get("user_id"), "student_001")

            logout_resp = self.client.post("/api/auth/logout", headers=headers)
            self.assertEqual(logout_resp.status_code, 200)
            logout_data = logout_resp.get_json()
            self.assertTrue(logout_data.get("success"))
            self.assertTrue(logout_data.get("logged_out"))

            expired_resp = self.client.get("/api/auth/me", headers=headers)
            self.assertEqual(expired_resp.status_code, 401)
            expired_data = expired_resp.get_json()
            self.assertFalse(expired_data.get("success"))
            self.assertEqual(expired_data.get("error_code"), "AUTH_REQUIRED")

    def test_login_contract_and_invalid_password(self):
        with self._patch_auth_storage():
            self.users["student_002"] = {
                "username": "student_002",
                "display_name": "学习者",
                "password_hash": backend_app.generate_password_hash("secret456"),
                "locale": "EN",
                "created_at": "2026-03-29T10:00:00",
                "updated_at": "2026-03-29T10:00:00",
                "last_login_at": None,
            }

            fail_resp = self.client.post("/api/auth/login", json={
                "username": "student_002",
                "password": "wrong-password",
            })
            self.assertEqual(fail_resp.status_code, 401)
            fail_data = fail_resp.get_json()
            self.assertFalse(fail_data.get("success"))
            self.assertEqual(fail_data.get("error_code"), "AUTH_INVALID_CREDENTIALS")

            ok_resp = self.client.post("/api/auth/login", json={
                "username": "student_002",
                "password": "secret456",
            })
            self.assertEqual(ok_resp.status_code, 200)
            ok_data = ok_resp.get_json()
            self.assertTrue(ok_data.get("success"))
            self.assertEqual(ok_data.get("auth", {}).get("user", {}).get("locale"), "EN")
            self.assertTrue(ok_data.get("auth", {}).get("token"))

    def test_authenticated_business_request_uses_login_user(self):
        with self._patch_auth_storage(), self._patch_plan_storage():
            register_resp = self.client.post("/api/auth/register", json={
                "username": "student_003",
                "password": "secret789",
                "display_name": "测试同学",
                "locale": "CN",
            })

            self.assertEqual(register_resp.status_code, 200)
            token = register_resp.get_json().get("auth", {}).get("token")
            headers = {"Authorization": f"Bearer {token}"}

            add_resp = self.client.post("/api/plans", headers=headers, json={
                "user_id": "other_user",
                "time": "09:30",
                "task": "复习导数",
            })
            self.assertEqual(add_resp.status_code, 200)
            self.assertIn("student_003", self.plan_store)
            self.assertNotIn("other_user", self.plan_store)
            self.assertEqual(self.plan_store["student_003"][0]["task"], "复习导数")

            list_resp = self.client.get("/api/plans?user_id=other_user", headers=headers)
            self.assertEqual(list_resp.status_code, 200)
            list_data = list_resp.get_json()
            self.assertTrue(list_data.get("success"))
            self.assertEqual(list_data.get("count"), 1)
            self.assertEqual(list_data.get("plans", [])[0].get("task"), "复习导数")

    def test_invalid_auth_token_blocks_business_request(self):
        with self._patch_auth_storage():
            resp = self.client.get("/api/plans?user_id=student_004", headers={
                "Authorization": "Bearer invalid-token"
            })
            self.assertEqual(resp.status_code, 401)
            data = resp.get_json()
            self.assertFalse(data.get("success"))
            self.assertEqual(data.get("error_code"), "AUTH_REQUIRED")

    def test_login_binds_guest_project_state(self):
        with self._patch_auth_storage(), self._patch_plan_storage(), self._patch_learning_state_storage():
            self.users["student_bind"] = {
                "username": "student_bind",
                "display_name": "已注册用户",
                "password_hash": backend_app.generate_password_hash("secret456"),
                "locale": "CN",
                "created_at": "2026-03-29T10:00:00",
                "updated_at": "2026-03-29T10:00:00",
                "last_login_at": None,
            }
            self.plan_store["default_user"] = [{
                "id": "plan-guest-1",
                "time": "09:00",
                "task": "复习极限",
                "completed": False,
                "created_at": "2026-03-30T08:00:00",
            }]
            self.knowledge_store["default_user"] = {
                "concepts": [{"concept": "导数", "mastery": 0.35, "review_count": 1}],
                "relations": [{"source": "极限", "target": "导数", "type": "前置", "score": 0.9}],
                "deleted_concepts": [],
            }
            self.event_store[("default_user", "content")] = [{
                "content_type": "note",
                "timestamp": "2026-03-30T09:20:00",
                "topics": ["导数"],
            }]
            self.space_store["default_user"] = {
                "activeEntrySpaceId": "space_guest_1",
                "spaces": [{
                    "id": "space_guest_1",
                    "name": "访客空间",
                    "createdAt": 1711771200000,
                    "updatedAt": 1711771200000,
                    "items": [{
                        "id": "item_guest_1",
                        "name": "访客笔记",
                        "kind": "note",
                        "mime": "text/plain",
                        "size": 12,
                        "source": "guest",
                        "content": "导数要点",
                        "summary": "访客内容",
                        "fileDataUrl": "",
                        "audioDataUrl": "",
                        "addedAt": 1711771200000,
                        "updatedAt": 1711771200000,
                    }]
                }]
            }

            ok_resp = self.client.post("/api/auth/login", json={
                "username": "student_bind",
                "password": "secret456",
                "guest_user_id": "default_user",
            })

            self.assertEqual(ok_resp.status_code, 200)
            ok_data = ok_resp.get_json()
            self.assertTrue(ok_data.get("success"))
            binding = ok_data.get("binding", {})
            self.assertTrue(binding.get("migrated"))
            self.assertEqual(binding.get("guest_user_id"), "default_user")
            self.assertEqual(binding.get("plans"), 1)
            self.assertEqual(binding.get("concepts"), 1)
            self.assertEqual(binding.get("relations"), 1)
            self.assertEqual(binding.get("events"), 1)

            self.assertIn("student_bind", self.plan_store)
            self.assertEqual(len(self.plan_store["student_bind"]), 1)
            self.assertEqual(self.plan_store["student_bind"][0]["task"], "复习极限")

            target_knowledge = self.knowledge_store.get("student_bind", {})
            self.assertEqual(target_knowledge.get("concepts", [])[0].get("concept"), "导数")
            self.assertEqual(target_knowledge.get("relations", [])[0].get("target"), "导数")

            target_events = self.event_store.get(("student_bind", "content"), [])
            self.assertEqual(len(target_events), 1)
            self.assertEqual(target_events[0].get("topics"), ["导数"])
            self.assertEqual(self.profile_store.get("student_bind", {}).get("user_id"), "student_bind")
            target_spaces = self.space_store.get("student_bind", {}).get("spaces", [])
            self.assertEqual(len(target_spaces), 1)
            self.assertEqual(target_spaces[0].get("name"), "访客空间")
            self.assertEqual(target_spaces[0].get("items", [])[0].get("name"), "访客笔记")

    def test_delete_account_contract_clears_user_and_session(self):
        with self._patch_auth_storage():
            register_resp = self.client.post("/api/auth/register", json={
                "username": "student_delete",
                "password": "secret123",
                "display_name": "删除测试",
                "locale": "CN",
            })

            self.assertEqual(register_resp.status_code, 200)
            token = register_resp.get_json().get("auth", {}).get("token")
            headers = {"Authorization": f"Bearer {token}"}

            self.plan_store["student_delete"] = [{
                "id": "plan-delete-1",
                "time": "18:00",
                "task": "整理纺织笔记",
                "completed": False,
            }]
            self.knowledge_store["student_delete"] = {
                "concepts": [{"concept": "纱线结构", "mastery": 0.42}],
                "relations": [],
                "deleted_concepts": [],
            }
            self.profile_store["student_delete"] = {
                "user_id": "student_delete",
                "updated_at": "2026-03-30T12:00:00",
            }
            self.event_store[("student_delete", "content")] = [{
                "content_type": "summary",
                "timestamp": "2026-03-30T12:30:00",
            }]

            delete_resp = self.client.delete("/api/auth/account", headers=headers)
            self.assertEqual(delete_resp.status_code, 200)
            delete_data = delete_resp.get_json()
            self.assertTrue(delete_data.get("success"))
            self.assertTrue(delete_data.get("deleted_account"))

            cleanup = delete_data.get("cleanup", {})
            self.assertTrue(cleanup.get("auth_user_deleted"))
            self.assertEqual(cleanup.get("sessions_deleted"), 1)
            self.assertEqual(cleanup.get("plans_deleted"), 1)
            self.assertEqual(cleanup.get("knowledge_deleted"), 1)
            self.assertEqual(cleanup.get("profile_deleted"), 1)
            self.assertEqual(cleanup.get("events_deleted"), 2)

            self.assertNotIn("student_delete", self.users)
            self.assertNotIn("student_delete", self.plan_store)
            self.assertNotIn("student_delete", self.knowledge_store)
            self.assertNotIn("student_delete", self.profile_store)
            self.assertNotIn(("student_delete", "content"), self.event_store)
            self.assertNotIn(("student_delete", "behavior"), self.event_store)

            me_resp = self.client.get("/api/auth/me", headers=headers)
            self.assertEqual(me_resp.status_code, 401)
            me_data = me_resp.get_json()
            self.assertFalse(me_data.get("success"))
            self.assertEqual(me_data.get("error_code"), "AUTH_REQUIRED")


if __name__ == "__main__":
    unittest.main()
