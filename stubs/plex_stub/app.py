from fastapi import FastAPI
from stubs.plex_stub.routers import identity, library, hubs, collections, images

app = FastAPI(title="Plex Stub Server")

app.include_router(identity.router)
app.include_router(library.router)
app.include_router(hubs.router)
app.include_router(collections.router)
app.include_router(images.router)


@app.post("/reset")
def reset_state():
    from stubs.plex_stub.state import state
    state.reset()
    return {"ok": True}
