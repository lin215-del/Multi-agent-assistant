from __future__ import annotations

import unittest
from unittest.mock import patch

import web_ragflow


class FakeClient(web_ragflow.WebRagflowClient):
    def __init__(self) -> None:
        self.calls = []

    def list_documents(self, dataset_id: str):
        return {"docs": [{"name": "already-there.md"}]}

    def request(self, method: str, path: str, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/documents") and method == "POST":
            return [
                {"id": f"doc-{index}", "name": item[1][0]}
                for index, item in enumerate(kwargs["files"])
            ]
        return None


class WebRagflowTests(unittest.TestCase):
    def test_localhost_is_allowed_only_in_private_mode(self) -> None:
        with patch.object(web_ragflow, "ALLOW_PRIVATE_RAGFLOW", True):
            self.assertEqual(web_ragflow.normalize_base_url("http://localhost:8080/api/v1"), "http://localhost:8080")
        with patch.object(web_ragflow, "ALLOW_PRIVATE_RAGFLOW", False):
            with self.assertRaises(web_ragflow.WebRagflowError):
                web_ragflow.normalize_base_url("http://localhost:8080")

    def test_remote_http_and_extra_paths_are_rejected(self) -> None:
        with self.assertRaises(web_ragflow.WebRagflowError):
            web_ragflow.normalize_base_url("http://example.com")
        with self.assertRaises(web_ragflow.WebRagflowError):
            web_ragflow.normalize_base_url("https://example.com/admin")

    def test_snapshot_catalog_and_blobs_are_complete(self) -> None:
        catalog = web_ragflow.snapshot_catalog()
        self.assertEqual(len(catalog), 5)
        core = next(item for item in catalog if "核心服务卡片" in item["name"])
        rows = web_ragflow.snapshot_documents(core["id"])
        self.assertEqual(len(rows), 34)
        for row in rows:
            self.assertTrue(web_ragflow.safe_snapshot_blob(row["blob_path"]).is_file())

    def test_snapshot_import_batches_and_triggers_parse(self) -> None:
        client = FakeClient()
        core = next(item for item in web_ragflow.snapshot_catalog() if "核心服务卡片" in item["name"])
        progress = []
        result = client.import_snapshot("target", core["id"], lambda *values: progress.append(values))
        self.assertEqual(result, {"uploaded": 34, "skipped": 0, "total": 34})
        upload_calls = [call for call in client.calls if call[0] == "POST" and call[1].endswith("/documents")]
        parse_calls = [call for call in client.calls if call[1].endswith("/documents/parse")]
        self.assertEqual(len(upload_calls), 5)
        self.assertEqual(len(parse_calls), 5)
        self.assertEqual(progress[-1], (34, 0, 34))


if __name__ == "__main__":
    unittest.main()
