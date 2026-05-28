import os

SECRET_KEY = os.getenv("SECRET_KEY", "clave_super_secreta_desarrollo_agm")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
ENABLE_GRPC_SERVER = os.getenv("ENABLE_GRPC_SERVER", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

RESET_PASSWORD_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("RESET_PASSWORD_TOKEN_EXPIRE_MINUTES", "30")
)
RESET_PASSWORD_EXPOSE_TOKEN = os.getenv(
    "RESET_PASSWORD_EXPOSE_TOKEN", "false"
).lower() in {"1", "true", "yes", "on"}

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672")
NOTIFICACIONES_TIMEOUT_SECONDS = float(
    os.getenv("NOTIFICACIONES_TIMEOUT_SECONDS", "3")
)
