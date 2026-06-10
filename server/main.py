"""C2 Framework — FastAPI Server Entrypoint."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import SERVER_HOST, SERVER_PORT
from server.database import init_db
from server.routes import router

app = FastAPI(title="C2 Framework API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {"service": "c2-framework", "version": "0.1.0", "status": "running"}


def main():
    uvicorn.run(
        "server.main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
