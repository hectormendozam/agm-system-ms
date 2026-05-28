import os
import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AGM API Gateway")

# Configuración de CORS ABIERTO PARA DESARROLLO
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mapeo de prefijos a hosts
SERVICES = {
    "auth": {"host": os.getenv("MS_AUTH_HOST", "ms-auth"), "port": 8000, "path_prefix": ""},
    "periodos": {"host": os.getenv("MS_PERIODOS_HOST", "ms-periodos-materias"), "port": 8000, "path_prefix": "api"},
    "materias": {"host": os.getenv("MS_PERIODOS_HOST", "ms-periodos-materias"), "port": 8000, "path_prefix": "api"},
    "docentes": {"host": os.getenv("MS_DOCENTES_HOST", "ms-docentes"), "port": 8003, "path_prefix": ""},
    "alumnos": {"host": os.getenv("MS_DOCENTES_HOST", "ms-docentes"), "port": 8003, "path_prefix": ""},
    "calificaciones": {"host": os.getenv("MS_CALIFICACIONES_HOST", "ms-calificaciones"), "port": 8004, "path_prefix": ""},
    "asistencias": {"host": os.getenv("MS_ASISTENCIAS_HOST", "ms-asistencias"), "port": 8005, "path_prefix": ""},
    "reportes": {"host": os.getenv("MS_REPORTES_HOST", "ms-reportes"), "port": 8007, "path_prefix": ""},
}

client = httpx.AsyncClient()

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Gateway FastAPI is RUNNING", "port": os.getenv("PORT", "9000")}

@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def proxy_api(request: Request, service: str, path: str):
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Servicio '{service}' no encontrado")

    config = SERVICES[service]
    target_host = config["host"]
    target_port = config["port"]
    prefix = config.get("path_prefix", "").strip("/")

    # Normalizar el path
    clean_path = path.strip("/")
    
    # Construir URL interna
    # Casi todos los microservicios esperan /nombre-servicio/endpoint
    # Django (periodos/materias) espera /api/nombre-servicio/endpoint/
    
    segments = []
    if prefix:
        segments.append(prefix)
    
    segments.append(service)
    
    if clean_path:
        segments.append(clean_path)
    
    internal_url = f"http://{target_host}:{target_port}/" + "/".join(segments)
    
    # Asegurar slash final para Django
    if service in ["periodos", "materias"] and not internal_url.endswith("/"):
        internal_url += "/"
    
    # Agregar query params si existen
    if request.query_params:
        internal_url += f"?{request.query_params}"

    print(f"--> [Proxy] {request.method} {request.url.path} -> {internal_url}")

    try:
        content = await request.body()
        original_headers = dict(request.headers)
        
        # Cabeceras permitidas
        allowed = ["authorization", "content-type", "accept", "user-agent", "origin", "referer"]
        headers = {k: v for k, v in original_headers.items() if k.lower() in allowed}

        response = await client.request(
            method=request.method,
            url=internal_url,
            content=content,
            headers=headers,
            timeout=20.0,
            follow_redirects=True
        )

        # Filtramos headers de CORS para evitar duplicados si el MS ya los envía
        resp_headers = dict(response.headers)
        for h in ["access-control-allow-origin", "access-control-allow-credentials", "access-control-allow-methods", "access-control-allow-headers", "content-length"]:
            resp_headers.pop(h, None)

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=resp_headers
        )
    except Exception as e:
        print(f"!! [Proxy Error] {str(e)}")
        raise HTTPException(status_code=502, detail=f"Error conectando a {service}: {str(e)}")

# Catch-all para rutas que no empiecen con /api/
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def catch_all(request: Request, path: str):
    # Si la ruta es directamente un servicio (ej: /auth/login), redirigir a /api/auth/login
    parts = path.strip("/").split("/")
    if parts and parts[0] in SERVICES:
        service = parts[0]
        remaining = "/".join(parts[1:])
        return await proxy_api(request, service, remaining)
    
    raise HTTPException(status_code=404, detail="Ruta no encontrada. Use /api/{servicio}/...")
