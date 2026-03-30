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


if __name__ == "__main__":
    unittest.main()
