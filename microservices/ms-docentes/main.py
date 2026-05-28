"""
main.py – Punto de entrada del MS-3: Docentes & Alumnos
Arranca FastAPI (REST) y lanza el servidor RabbitMQ RPC en un hilo daemon separado.
Patrón idéntico a ms-auth para coherencia arquitectónica.
"""
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from database import engine, Base
from src.controllers.docentes_controller import router as docentes_router
from src.controllers.alumnos_controller import router as alumnos_router

# ── 1. Crear tablas en la BD si no existen ────────────────────────────────────
Base.metadata.create_all(bind=engine)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE alumnos ADD COLUMN IF NOT EXISTS numero_registro INTEGER"))
    conn.execute(text("ALTER TABLE docentes ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE"))

# ── 2. Inicializar la aplicación FastAPI ─────────────────────────────────────
app = FastAPI(
    title="MS-3 Docentes & Alumnos",
    description=(
        "Microservicio de importación y gestión de Docentes y Alumnos del sistema AGM. "
        "Procesa PDF de programación académica y PDF de alumnos inscritos por materia."
    ),
    version="1.0.0",
)

origins = [
    "https://agm-system-frontend-joselyn-agm.vercel.app",
    "https://agm-system-frontend-30ytwlq1y-joselyn-agm.vercel.app",
    "https://agm-system-frontend.vercel.app",
    "http://localhost:4200",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 3. Registrar routers ──────────────────────────────────────────────────────
app.include_router(docentes_router)
app.include_router(alumnos_router)


# ── 4. Health-check raíz ─────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def health_check():
    return {"mensaje": "¡MS-3 Docentes & Alumnos está corriendo!", "version": "1.0.0"}


# ── 5. Lanzar RabbitMQ RPC + ImportWorker en hilos daemon al iniciar FastAPI ──
@app.on_event("startup")
def start_background_workers():
    import rabbitmq_server
    from src import import_worker
    t_rpc = threading.Thread(target=rabbitmq_server.serve, daemon=True, name="rpc-server")
    t_rpc.start()
    t_worker = threading.Thread(target=import_worker.serve, daemon=True, name="import-worker")
    t_worker.start()


# ── 6. Punto de entrada para ejecución directa ───────────────────────────────
if __name__ == "__main__":
    import os
    port = int(os.getenv("REST_PORT", 8003))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
