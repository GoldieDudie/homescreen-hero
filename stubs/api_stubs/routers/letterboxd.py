from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from stubs.api_stubs.fixture_loader import FIXTURES_DIR

router = APIRouter(prefix="/letterboxd")


@router.get("/{path:path}")
def serve_list_page(path: str):
    # Serve static HTML that BeautifulSoup can parse
    html_file = FIXTURES_DIR / "letterboxd" / "list_page.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())

    # Default empty list page
    return HTMLResponse(content="""
    <html><body>
    <ul class="js-list-entries poster-list">
    </ul>
    </body></html>
    """)
