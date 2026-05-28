import os
import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AGM API Gateway")

# Configuración de CORS
# origins = [
#     "https://agm-system-frontend-joselyn-agm.vercel.app",
#     "https://agm-system-frontend-30ytwlq1y-joselyn-agm.vercel.app",
#     "https://agm-system-frontend.vercel.app",
#     "http://localhost:4200",
# ]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# CORS ABIERTO PARA DESARROLLO
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mapeo de prefijos a hosts
SERVICES = {
    "auth": {"host": os.getenv("MS_AUTH_HOST"), "port": 8000, "path_prefix": ""},
    # ms-periodos-materias expone sus endpoints bajo /api/, indicar prefijo
    "periodos": {"host": os.getenv("MS_PERIODOS_HOST"), "port": 8000, "path_prefix": "api"},
    "docentes": {"host": os.getenv("MS_DOCENTES_HOST"), "port": 8003, "path_prefix": ""},
    "calificaciones": {"host": os.getenv("MS_CALIFICACIONES_HOST"), "port": 8004, "path_prefix": ""},
    "asistencias": {"host": os.getenv("MS_ASISTENCIAS_HOST"), "port": 8005, "path_prefix": ""},
    "reportes": {"host": os.getenv("MS_REPORTES_HOST"), "port": 8007, "path_prefix": ""},
}

client = httpx.AsyncClient()

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Gateway FastAPI is RUNNING", "port": os.getenv("PORT", "80")}

@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def proxy_api(request: Request, service: str, path: str):
    return await proxy(request, service, path)

@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def proxy(request: Request, service: str, path: str):
    if service not in SERVICES:
        print(f"!! [Proxy Error] Servicio '{service}' no encontrado (Path: {path})")
        raise HTTPException(status_code=404, detail=f"Servicio '{service}' no encontrado")

    config = SERVICES[service]
    target_host = config["host"]
    target_port = config["port"]

    if not target_host:
        raise HTTPException(status_code=502, detail=f"Host no configurado para: {service}")

    # Construir URL objetivo. Algunos microservicios exponen su API bajo un prefijo
    # (p.ej. ms-periodos-materias usa '/api/'). Respetamos el prefijo definido.
    prefix = config.get("path_prefix", "")
    if prefix:
        url = f"http://{target_host}:{target_port}/{prefix}/{path}"
    else:
        url = f"http://{target_host}:{target_port}/{path}"
    # Si por accidente el frontend concatena dos veces 'api' (p.ej. /api/periodos/api/materias),
    # colapsamos '/api/api/' a '/api/' para evitar 400 por rutas inválidas.
    url = url.replace('/api/api/', '/api/')
    if request.query_params:
        url += f"?{request.query_params}"

    print(f"--> [Proxy] {request.method} -> {url}")

    try:
        content = await request.body()
        original_headers = dict(request.headers)
        # Filtrar y reenviar solo las cabeceras necesarias para evitar duplicados
        allowed = ["authorization", "content-type", "accept", "user-agent", "origin", "referer", "cookie"]
        headers = {}
        for k, v in original_headers.items():
            if k.lower() in allowed:
                headers[k] = v

        response = await client.request(
            method=request.method,
            url=url,
            content=content,
            headers=headers,
            timeout=15.0,
            follow_redirects=True
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
