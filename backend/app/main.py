from fastapi import FastAPI

from .db import Base, engine
from .routes import router
from .security import RetellSignatureMiddleware

app = FastAPI(title="FMRI Gurgaon Receptionist Backend")
app.add_middleware(RetellSignatureMiddleware)
app.include_router(router)

Base.metadata.create_all(engine)


@app.get("/health")
async def health():
    return {"ok": True}
