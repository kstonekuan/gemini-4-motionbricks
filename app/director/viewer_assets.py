"""Viewer file policy; Starlette owns path lookup and HTTP file semantics."""

from pathlib import Path

from fastapi import FastAPI
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class ViewerAssets(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # Revalidate even hashed assets: this viewer may be replaced in place.
        response.headers["Cache-Control"] = "no-cache"
        return response


def mount_viewer_assets(application: FastAPI, assets_path: Path) -> None:
    """Mount last so viewer files cannot shadow command or WebSocket routes."""

    @application.get("/vnc.html", include_in_schema=False)
    async def legacy_viewer() -> RedirectResponse:
        return RedirectResponse("./", status_code=302)

    application.mount("/", ViewerAssets(directory=assets_path, html=True))
