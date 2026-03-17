from fastapi import FastAPI
from stubs.api_stubs.routers import tautulli, trakt, mdblist, tmdb, seerr, anilist, mal, letterboxd

app = FastAPI(title="API Stubs Server")

app.include_router(tautulli.router)
app.include_router(trakt.router)
app.include_router(mdblist.router)
app.include_router(tmdb.router)
app.include_router(seerr.router)
app.include_router(anilist.router)
app.include_router(mal.router)
app.include_router(letterboxd.router)
