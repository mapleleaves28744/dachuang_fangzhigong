import copy
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

try:
    from app import server as backend_app
    _APP_IMPORT_ERROR = ""
except Exception as e:
    backend_app = None
    _APP_IMPORT_ERROR = str(e)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestSpaceContract(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()
        self.space_store = {}
        self.users = {}
        self.sessions = {}
        self.event_store = {}

    def _set_guest_cookie(self, client, guest_user_id):
        signed = backend_app.sign_guest_session_cookie_value(guest_user_id)
        client.set_cookie(backend_app.GUEST_SESSION_COOKIE_NAME, signed, domain="localhost")

    def _patch_space_storage(self):
        def get_user_space_payload(user_id):
            payload = self.space_store.get(user_id, {"activeEntrySpaceId": "", "spaces": []})
            return copy.deepcopy(payload)

        def set_user_space_payload(user_id, payload):
            self.space_store[user_id] = copy.deepcopy(payload)

        return patch.multiple(
            backend_app,
            get_user_space_payload=get_user_space_payload,
            set_user_space_payload=set_user_space_payload,
        )

    def _patch_auth_storage(self):
        def get_auth_user(username):
            item = self.users.get(username)
            return copy.deepcopy(item) if item else None

        def get_auth_user_by_display_name(display_name):
            lookup = str(display_name or "").strip().casefold()
            if not lookup:
                return None
            for item in self.users.values():
                item_display_name = str((item or {}).get("display_name") or "").strip().casefold()
                if item_display_name == lookup:
                    return copy.deepcopy(item)
            return None

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
            return {
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

        return patch.multiple(
            backend_app,
            delete_auth_user_account=delete_auth_user_account,
            get_auth_user=get_auth_user,
            get_auth_user_by_display_name=get_auth_user_by_display_name,
            upsert_auth_user=upsert_auth_user,
            get_auth_session_by_token_hash=get_auth_session_by_token_hash,
            upsert_auth_session=upsert_auth_session,
            revoke_auth_session=revoke_auth_session,
            touch_auth_session=touch_auth_session,
            append_user_event=append_user_event,
        )

    def test_space_crud_and_preview_contract(self):
        with self._patch_space_storage():
            create_resp = self.client.post("/api/spaces", json={
                "user_id": "space_user",
                "name": "云端纺织资料",
            })
            self.assertEqual(create_resp.status_code, 200)
            create_data = create_resp.get_json()
            self.assertTrue(create_data.get("success"))

            space = create_data.get("space", {})
            space_id = space.get("id")
            self.assertTrue(space_id)

            add_resp = self.client.post(f"/api/spaces/{space_id}/items", json={
                "user_id": "space_user",
                "items": [{
                    "name": "整理笔记.txt",
                    "kind": "note",
                    "mime": "text/plain",
                    "size": 6,
                    "source": "upload",
                    "content": "纺织结构",
                    "summary": "",
                    "fileDataUrl": "data:text/plain;base64,aGVsbG8=",
                }]
            })
            self.assertEqual(add_resp.status_code, 200)
            add_data = add_resp.get_json()
            self.assertTrue(add_data.get("success"))
            self.assertEqual(add_data.get("createdCount"), 1)
            item = add_data.get("items", [])[0]
            item_id = item.get("id")
            self.assertTrue(item.get("previewUrl"))
            self.assertIn("preview_signature=", item.get("previewUrl"))
            self.assertNotIn("preview_token=", item.get("previewUrl"))
            self.assertNotIn("auth_token=", item.get("previewUrl"))
            self.assertNotIn("user_id=", item.get("previewUrl"))

            list_resp = self.client.get("/api/spaces?user_id=space_user")
            self.assertEqual(list_resp.status_code, 200)
            list_data = list_resp.get_json()
            self.assertEqual(list_data.get("count"), 1)
            self.assertEqual(list_data.get("spaces", [])[0].get("itemCount"), 1)

            rename_resp = self.client.put(f"/api/spaces/{space_id}", json={
                "user_id": "space_user",
                "name": "纺织复习空间",
                "description": "整理纺织结构与工艺资料",
            })
            self.assertEqual(rename_resp.status_code, 200)
            rename_data = rename_resp.get_json()
            self.assertEqual(rename_data.get("space", {}).get("name"), "纺织复习空间")
            self.assertEqual(rename_data.get("space", {}).get("description"), "整理纺织结构与工艺资料")

            rename_post_resp = self.client.post(f"/api/spaces/{space_id}", json={
                "user_id": "space_user",
                "description": "课堂资料与工艺要点",
            })
            self.assertEqual(rename_post_resp.status_code, 200)
            rename_post_data = rename_post_resp.get_json()
            self.assertEqual(rename_post_data.get("space", {}).get("description"), "课堂资料与工艺要点")

            detail_resp = self.client.get(f"/api/spaces/items/{item_id}?user_id=space_user")
            self.assertEqual(detail_resp.status_code, 200)
            detail_data = detail_resp.get_json()
            self.assertEqual(detail_data.get("item", {}).get("name"), "整理笔记.txt")
            self.assertIn("hello", detail_data.get("item", {}).get("content", ""))

            preview_parts = urlsplit(str(item.get("previewUrl") or ""))
            preview_path = preview_parts.path + (f"?{preview_parts.query}" if preview_parts.query else "")
            preview_resp = self.client.get(preview_path)
            self.assertEqual(preview_resp.status_code, 200)
            self.assertEqual(preview_resp.mimetype, "text/plain")
            self.assertIn("hello", preview_resp.get_data(as_text=True))

            update_resp = self.client.put(f"/api/spaces/items/{item_id}", json={
                "user_id": "space_user",
                "name": "整理后的笔记.txt",
                "content": "纺织结构与工艺",
            })
            self.assertEqual(update_resp.status_code, 200)
            update_data = update_resp.get_json()
            self.assertEqual(update_data.get("item", {}).get("name"), "整理后的笔记.txt")

            update_post_resp = self.client.post(f"/api/spaces/items/{item_id}", json={
                "user_id": "space_user",
                "name": "整理后的课堂笔记.txt",
            })
            self.assertEqual(update_post_resp.status_code, 200)
            update_post_data = update_post_resp.get_json()
            self.assertEqual(update_post_data.get("item", {}).get("name"), "整理后的课堂笔记.txt")

            second_space_resp = self.client.post("/api/spaces", json={
                "user_id": "space_user",
                "name": "移动目标空间",
            })
            self.assertEqual(second_space_resp.status_code, 200)
            second_space_id = second_space_resp.get_json().get("space", {}).get("id")

            move_resp = self.client.put(f"/api/spaces/items/{item_id}", json={
                "user_id": "space_user",
                "targetSpaceId": second_space_id,
            })
            self.assertEqual(move_resp.status_code, 200)
            move_data = move_resp.get_json()
            self.assertEqual(move_data.get("space", {}).get("id"), second_space_id)
            self.assertEqual(move_data.get("sourceSpace", {}).get("id"), space_id)

            moved_list = self.client.get("/api/spaces?user_id=space_user").get_json()
            moved_spaces = {item.get("id"): item for item in moved_list.get("spaces", [])}
            self.assertEqual(moved_spaces.get(space_id, {}).get("itemCount"), 0)
            self.assertEqual(moved_spaces.get(second_space_id, {}).get("itemCount"), 1)

            delete_item_resp = self.client.delete(f"/api/spaces/items/{item_id}?user_id=space_user")
            self.assertEqual(delete_item_resp.status_code, 200)
            delete_item_data = delete_item_resp.get_json()
            self.assertTrue(delete_item_data.get("deleted"))
            self.assertEqual(delete_item_data.get("spaceId"), second_space_id)

            after_item_delete = self.client.get("/api/spaces?user_id=space_user").get_json()
            after_item_spaces = {item.get("id"): item for item in after_item_delete.get("spaces", [])}
            self.assertEqual(after_item_spaces.get(second_space_id, {}).get("itemCount"), 0)

            delete_resp = self.client.delete(f"/api/spaces/{space_id}?user_id=space_user")
            self.assertEqual(delete_resp.status_code, 200)
            delete_data = delete_resp.get_json()
            self.assertTrue(delete_data.get("deleted"))

            delete_second_resp = self.client.delete(f"/api/spaces/{second_space_id}?user_id=space_user")
            self.assertEqual(delete_second_resp.status_code, 200)

            final_list = self.client.get("/api/spaces?user_id=space_user").get_json()
            self.assertEqual(final_list.get("count"), 0)

    def test_authenticated_space_request_uses_login_user(self):
        with self._patch_space_storage(), self._patch_auth_storage():
            register_resp = self.client.post("/api/auth/register", json={
                "username": "space_auth_user",
                "password": "secret123",
                "display_name": "空间用户",
                "locale": "CN",
            })
            self.assertEqual(register_resp.status_code, 200)
            token = register_resp.get_json().get("auth", {}).get("token")
            headers = {"Authorization": f"Bearer {token}"}

            create_resp = self.client.post("/api/spaces", headers=headers, json={
                "user_id": "other_user",
                "name": "应绑定到登录账号",
            })
            self.assertEqual(create_resp.status_code, 200)

            list_resp = self.client.get("/api/spaces?user_id=other_user", headers=headers)
            self.assertEqual(list_resp.status_code, 200)
            list_data = list_resp.get_json()
            self.assertEqual(list_data.get("user_id"), "space_auth_user")
            self.assertEqual(list_data.get("count"), 1)
            self.assertEqual(list_data.get("spaces", [])[0].get("name"), "应绑定到登录账号")

    def test_anonymous_space_request_cannot_read_other_user_space_via_query_user_id(self):
        with self._patch_space_storage():
            guest_user_id = "guest_spacecase1234"
            self._set_guest_cookie(self.client, guest_user_id)
            self.space_store[guest_user_id] = {
                "activeEntrySpaceId": "space_guest_1",
                "spaces": [{"id": "space_guest_1", "name": "我的空间", "items": []}],
            }
            self.space_store["victim_user"] = {
                "activeEntrySpaceId": "space_victim_1",
                "spaces": [{"id": "space_victim_1", "name": "别人的空间", "items": []}],
            }

            resp = self.client.get("/api/spaces?user_id=victim_user")

            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("user_id"), guest_user_id)
            self.assertEqual(data.get("spaces", [])[0].get("name"), "我的空间")

    def test_first_anonymous_space_request_issues_guest_scope_instead_of_query_user_id(self):
        with self._patch_space_storage():
            self.space_store["victim_user"] = {
                "activeEntrySpaceId": "space_victim_1",
                "spaces": [{"id": "space_victim_1", "name": "别人的空间", "items": []}],
            }

            resp = self.client.get("/api/spaces?user_id=victim_user")

            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertNotEqual(data.get("user_id"), "victim_user")
            self.assertTrue(str(data.get("user_id") or "").startswith("guest_"))
            self.assertEqual(data.get("count"), 0)
            self.assertIn(backend_app.GUEST_SESSION_COOKIE_NAME, resp.headers.get("Set-Cookie", ""))

    def test_space_preview_accepts_authorization_header_without_query_signature(self):
        with self._patch_space_storage(), self._patch_auth_storage():
            register_resp = self.client.post("/api/auth/register", json={
                "username": "space_preview_user",
                "password": "secret123",
                "display_name": "预览用户",
                "locale": "CN",
            })
            self.assertEqual(register_resp.status_code, 200)
            token = register_resp.get_json().get("auth", {}).get("token")
            headers = {"Authorization": f"Bearer {token}"}

            create_resp = self.client.post("/api/spaces", headers=headers, json={"name": "授权预览空间"})
            self.assertEqual(create_resp.status_code, 200)
            space_id = create_resp.get_json().get("space", {}).get("id")

            add_resp = self.client.post(
                f"/api/spaces/{space_id}/items",
                headers=headers,
                json={
                    "items": [{
                        "name": "授权预览.txt",
                        "kind": "note",
                        "mime": "text/plain",
                        "source": "upload",
                        "content": "只通过 Authorization 读取。",
                        "fileDataUrl": "data:text/plain;base64,QXV0aG9yaXphdGlvbiBvbmx5IHByZXZpZXcu",
                    }]
                },
            )
            self.assertEqual(add_resp.status_code, 200)
            preview_url = str(add_resp.get_json().get("items", [])[0].get("previewUrl") or "")
            preview_parts = urlsplit(preview_url)

            preview_resp = self.client.get(preview_parts.path, headers=headers)

            self.assertEqual(preview_resp.status_code, 200)
            self.assertEqual(preview_resp.mimetype, "text/plain")
            self.assertIn("Authorization only preview.", preview_resp.get_data(as_text=True))

    def test_space_image_upload_uses_ocr_text_and_exposes_ingest_metadata(self):
        with self._patch_space_storage(), patch.object(
            backend_app,
            "extract_text_from_image_service",
            return_value={
                "success": True,
                "text": "链式法则用于复合函数求导，先求外层导数再乘以内层导数。",
                "provider": "mock_local_fallback",
                "fallback_used": True,
                "error_code": "OCR_PROVIDER_DISABLED",
            },
        ):
            create_resp = self.client.post("/api/spaces", json={
                "user_id": "space_user",
                "name": "拍题空间",
            })
            self.assertEqual(create_resp.status_code, 200)
            space_id = create_resp.get_json().get("space", {}).get("id")

            add_resp = self.client.post(f"/api/spaces/{space_id}/items", json={
                "user_id": "space_user",
                "items": [{
                    "name": "链式法则拍题.png",
                    "kind": "image",
                    "mime": "image/png",
                    "source": "camera",
                    "summary": "",
                    "fileDataUrl": "data:image/png;base64,aGVsbG8=",
                }]
            })
            self.assertEqual(add_resp.status_code, 200)
            item = add_resp.get_json().get("items", [])[0]
            self.assertIn("链式法则", item.get("content", ""))
            self.assertEqual(item.get("textExtractMethod"), "image_ocr")
            self.assertGreaterEqual(int(item.get("textChunkCount") or 0), 1)
            self.assertTrue(item.get("retrievalReady"))
            self.assertEqual(item.get("ocrProvider"), "mock_local_fallback")
            self.assertTrue(item.get("ocrFallbackUsed"))


if __name__ == "__main__":
    unittest.main()
