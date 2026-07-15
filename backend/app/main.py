from fastapi import FastAPI

from .db import Base, engine
from .routes import router
from .security import RetellSignatureMiddleware
from .webcall import router as webcall_router

app = FastAPI(title="FMRI Gurgaon Receptionist Backend")
app.add_middleware(RetellSignatureMiddleware)
app.include_router(router)
app.include_router(webcall_router)

Base.metadata.create_all(engine)


@app.get("/health")
async def health():
    return {"ok": True}
