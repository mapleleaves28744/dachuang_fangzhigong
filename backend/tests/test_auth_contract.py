import copy
import unittest
from unittest.mock import patch

try:
    import app as backend_app
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

        return patch.multiple(
            backend_app,
            get_auth_user=get_auth_user,
            upsert_auth_user=upsert_auth_user,
            get_auth_session_by_token_hash=get_auth_session_by_token_hash,
            upsert_auth_session=upsert_auth_session,
            revoke_auth_session=revoke_auth_session,
            touch_auth_session=touch_auth_session,
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


if __name__ == "__main__":
    unittest.main()
