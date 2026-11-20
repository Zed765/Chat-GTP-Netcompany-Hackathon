from fastapi import FastAPI

from mock_upstream.chat import router as chat_router
from mock_upstream.settings import get_settings

# Read at import, so that a missing key stops the server with one line before it starts.
get_settings()

app = FastAPI(title="A.S.P.I.D.A. mock upstream", version="0.1.0")
app.include_router(chat_router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
