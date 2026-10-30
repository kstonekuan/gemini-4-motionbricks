"""Viewer deployment policy at the actual HTTP boundary, without GPU startup."""

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.director.viewer_assets import mount_viewer_assets


class ViewerAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_revalidates_after_deployment_and_preserves_proxy_links(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            assets_path = Path(temporary_directory)
            index_path = assets_path / "index.html"
            index_path.write_text("first viewer")
            application = FastAPI()
            mount_viewer_assets(application, assets_path)
            async with AsyncClient(
                transport=ASGITransport(app=application, root_path="/motionbricks"),
                base_url="http://viewer.test",
            ) as client:
                response = await client.get("/motionbricks/")
                self.assertEqual(response.text, "first viewer")
                self.assertEqual(response.headers["cache-control"], "no-cache")
                self.assertEqual((await client.head("/motionbricks/")).status_code, 200)
                revalidated = await client.get(
                    "/motionbricks/",
                    headers={"If-None-Match": response.headers["etag"]},
                )
                self.assertEqual(revalidated.status_code, 304)
                self.assertEqual(revalidated.headers["cache-control"], "no-cache")
                index_path.write_text("replacement viewer")
                updated = await client.get(
                    "/motionbricks/",
                    headers={"If-None-Match": response.headers["etag"]},
                )
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.text, "replacement viewer")
                legacy = await client.get(
                    "/motionbricks/vnc.html", follow_redirects=False
                )
                self.assertEqual(legacy.status_code, 302)
                self.assertEqual(legacy.headers["location"], "./")

    async def test_only_viewer_files_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            checkout_path = Path(temporary_directory)
            assets_path = checkout_path / "dist"
            assets_path.mkdir()
            secret_path = checkout_path / ".env"
            secret_path.write_text("private deployment configuration")
            (assets_path / "outside.txt").symlink_to(secret_path)
            application = FastAPI()
            mount_viewer_assets(application, assets_path)
            async with AsyncClient(
                transport=ASGITransport(app=application), base_url="http://viewer.test"
            ) as client:
                for requested_path in ("/%2e%2e/.env", "/outside.txt", "/missing.js"):
                    with self.subTest(path=requested_path):
                        response = await client.get(requested_path)
                        self.assertEqual(response.status_code, 404)
                        self.assertNotIn("private deployment", response.text)
