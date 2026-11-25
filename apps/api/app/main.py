import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.market.provider import provider
from app.pipeline import attach, detach
from app.routers import health, market, paper, signals, stream
from app.ws_hub import hub


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.bind(asyncio.get_running_loop())
    attach()
    if settings.boot_binance:
        await provider.start()
    try:
        yield
    finally:
        detach()
        await provider.stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(market.router)
app.include_router(paper.router)
app.include_router(signals.router)
app.include_router(stream.router)
