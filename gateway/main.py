import os
import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AGM API Gateway")

# Configuración de CORS
origins = [
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "https://agm-system-frontend.vercel.app",
    "https://agm-system-frontend-joselyn-agm.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mapeo de prefijos a hosts
SERVICES = {
    "auth": {"host": os.getenv("MS_AUTH_HOST"), "port": 8000},
    "periodos": {"host": os.getenv("MS_PERIODOS_HOST"), "port": 8000},
    "docentes": {"host": os.getenv("MS_DOCENTES_HOST"), "port": 8003},
    "calificaciones": {"host": os.getenv("MS_CALIFICACIONES_HOST"), "port": 8004},
    "asistencias": {"host": os.getenv("MS_ASISTENCIAS_HOST"), "port": 8005},
    "reportes": {"host": os.getenv("MS_REPORTES_HOST"), "port": 8007},
}

client = httpx.AsyncClient()

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Gateway FastAPI is RUNNING", "port": os.getenv("PORT", "80")}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def catch_all(request: Request, path: str):
    # path contiene la ruta completa después del host
    # ej: api/auth/usuarios/ o auth/usuarios/
    
    # 1. Limpiamos y normalizamos el path para extraer el servicio
    full_path = path.lstrip("/")
    if not full_path:
        return {"message": "AGM Gateway Root"}

    parts = full_path.split("/")
    
    # Manejar prefijo /api/
    if parts[0] == "api":
        if len(parts) < 2:
            raise HTTPException(status_code=404, detail="Debe especificar un servicio tras /api/")
        service = parts[1]
        # Reconstruimos el resto de la ruta preservando la estructura original
        # Buscamos dónde empieza el subpath después de 'api' y 'service'
        prefix_to_remove = f"api/{service}/"
        if full_path.startswith(prefix_to_remove):
            subpath = full_path[len(prefix_to_remove):]
        else:
            # Caso especial: /api/auth (sin slash final)
            subpath = ""
    else:
        service = parts[0]
        prefix_to_remove = f"{service}/"
        if full_path.startswith(prefix_to_remove):
            subpath = full_path[len(prefix_to_remove):]
        else:
            subpath = ""

    return await handle_proxy(request, service, subpath)

async def handle_proxy(request: Request, service: str, path: str):
    if service not in SERVICES:
        print(f"!! [Proxy Error] Servicio '{service}' no encontrado (Path: {path})")
        raise HTTPException(status_code=404, detail=f"Servicio '{service}' no encontrado")

    config = SERVICES[service]
    target_host = config["host"]
    target_port = config["port"]

    if not target_host:
        raise HTTPException(status_code=502, detail=f"Host no configurado para: {service}")

    forwarded_path = path
    if service == "auth":
        forwarded_path = f"auth/{path}" if path else "auth"

    url = f"http://{target_host}:{target_port}/{forwarded_path}"
    if request.query_params:
        url += f"?{request.query_params}"

    print(f"--> [Proxy] {request.method} -> {url}")

    try:
        content = await request.body()
        headers = dict(request.headers)
        
        # Headers estándar de Proxy para que el microservicio sepa quién es el cliente real
        headers.pop("host", None)
        headers["X-Forwarded-Host"] = request.url.netloc
        headers["X-Forwarded-Proto"] = request.url.scheme
        headers["X-Forwarded-For"] = request.client.host if request.client else ""

        response = await client.request(
            method=request.method,
            url=url,
            content=content,
            headers=headers,
            timeout=20.0
        )

        # Filtramos headers de CORS para evitar duplicados
        resp_headers = dict(response.headers)
        for h in ["access-control-allow-origin", "access-control-allow-credentials", "access-control-allow-methods", "access-control-allow-headers"]:
            resp_headers.pop(h, None)

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=resp_headers
        )
    except Exception as e:
        print(f"!! [Proxy Error] {str(e)}")
        raise HTTPException(status_code=502, detail=f"Error conectando a {service}: {str(e)}")
