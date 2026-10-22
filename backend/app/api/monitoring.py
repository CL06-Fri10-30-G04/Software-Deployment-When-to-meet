from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from ..paths import FRONTEND_DIR
from .deps import current_user, require_admin
from .errors import ApiError

MONITORING_PAGE = "monitoring.html"

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
page_router = APIRouter(include_in_schema=False)

_FORBIDDEN_PAGE = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Monitoring</title>
    <link rel="stylesheet" href="./css/style.css" />
  </head>
  <body>
    <main>
      <section class="card">
        <h1>Monitoring</h1>
        <p role="alert">Only Admin users can view monitoring.</p>
        <p><a href="meetings.html">Back to meetings</a></p>
      </section>
    </main>
  </body>
</html>
"""


@router.get("/live")
def live_metrics(
    request: Request, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    monitoring = request.app.state.monitoring
    return {
        "system": monitoring.sampler.snapshot(),
        "requests": monitoring.requests.summary(),
    }


@router.get("/azure")
def azure_metrics(
    request: Request,
    range: Literal["1h", "6h", "24h"] = "1h",
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return request.app.state.monitoring.azure.read(range)


@page_router.get("/monitoring.html")
def monitoring_page(request: Request) -> Response:
    """Serve the page only to Admins; the static files mount refuses it."""
    try:
        user = current_user(request)
    except ApiError:
        return RedirectResponse("login.html", status_code=303)
    if user.get("role") != "Admin":
        return HTMLResponse(_FORBIDDEN_PAGE, status_code=403)
    return FileResponse(FRONTEND_DIR / MONITORING_PAGE, headers={"Cache-Control": "no-store"})
