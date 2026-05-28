import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from notification_client import send_reset_password_email
from settings import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    RESET_PASSWORD_EXPOSE_TOKEN,
    RESET_PASSWORD_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
)
from fastapi.middleware.cors import CORSMiddleware
import models
import schemas


# Inicializa las tablas en la base de datos de PostgreSQL si no existen.
Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

app = FastAPI(
    title="MS-1 Auth & Users",
    description="Microservicio de Autenticacion para el sistema AGM",
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


import hashlib

def get_password_hash(password: str) -> str:
    # Usar SHA-256 con un salt fijo para máxima predictibilidad entre microservicios
    # manteniendo un nivel de seguridad adecuado para el proyecto.
    salt = "agm_system_fixed_salt_2026"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return get_password_hash(plain_password) == hashed_password


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_usuario_actual(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credenciales_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        usuario_id: str = payload.get("sub")
        if usuario_id is None:
            raise credenciales_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token ha caducado",
        )
    except jwt.InvalidTokenError:
        raise credenciales_exception

    usuario = db.query(models.Usuario).filter(models.Usuario.id == int(usuario_id)).first()
    if usuario is None:
        raise credenciales_exception

    return usuario


@app.get("/")
def read_root():
    return {"mensaje": "El microservicio de Auth esta corriendo"}


@app.post("/usuarios/", response_model=schemas.UsuarioResponse)
def crear_usuario(usuario: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.Usuario).filter(models.Usuario.email == usuario.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Este correo ya esta registrado")

    nuevo_usuario = models.Usuario(
        email=usuario.email,
        password_hash=get_password_hash(usuario.password),
        rol=usuario.rol,
    )

    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)

    return nuevo_usuario


@app.post("/auth/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    db_user = db.query(models.Usuario).filter(models.Usuario.email == form_data.username).first()

    if not db_user or not verify_password(form_data.password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contrasena incorrectos",
        )

    access_token = create_access_token(
        data={"sub": str(db_user.id), "rol": db_user.rol.value}
    )

    return {"access_token": access_token, "token_type": "bearer"}


@app.post(
    "/auth/forgot-password",
    response_model=schemas.ForgotPasswordResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def forgot_password(
    request: schemas.ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    response = schemas.ForgotPasswordResponse(
        message=(
            "Si el correo esta registrado, se enviara un enlace de recuperacion."
        )
    )

    usuario = db.query(models.Usuario).filter(models.Usuario.email == request.email).first()
    if usuario is None:
        return response

    now = datetime.now(timezone.utc)
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.usuario_id == usuario.id,
        models.PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    reset_token = secrets.token_urlsafe(32)
    db_token = models.PasswordResetToken(
        usuario_id=usuario.id,
        token_hash=hash_reset_token(reset_token),
        expires_at=now + timedelta(minutes=RESET_PASSWORD_TOKEN_EXPIRE_MINUTES),
    )
    db.add(db_token)
    db.commit()

    send_reset_password_email(usuario.email, reset_token)

    if RESET_PASSWORD_EXPOSE_TOKEN:
        response.reset_token = reset_token

    return response


@app.post("/auth/reset-password", response_model=schemas.MessageResponse)
def reset_password(
    request: schemas.ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    token_hash = hash_reset_token(request.token)

    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token_hash == token_hash,
        models.PasswordResetToken.used_at.is_(None),
        models.PasswordResetToken.expires_at > now,
    ).first()
    if reset_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de recuperacion invalido o expirado",
        )

    usuario = db.query(models.Usuario).filter(
        models.Usuario.id == reset_token.usuario_id
    ).first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de recuperacion invalido o expirado",
        )

    usuario.password_hash = get_password_hash(request.new_password)
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.usuario_id == usuario.id,
        models.PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.commit()

    return schemas.MessageResponse(message="Contrasena actualizada correctamente")


@app.get("/usuarios/", response_model=list[schemas.UsuarioResponse])
def obtener_usuarios(db: Session = Depends(get_db)):
    usuarios = db.query(models.Usuario).all()
    return usuarios


@app.get("/auth/me", response_model=schemas.UsuarioResponse)
def leer_usuario_actual(usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    return usuario_actual


def _start_rabbitmq():
    try:
        import rabbitmq_server
        rabbitmq_server.serve()
    except Exception as exc:
        print(f"[WARNING] No se pudo iniciar el servidor RabbitMQ-RPC de ms-auth: {exc}")


@app.on_event("startup")
def startup_event():
    # Iniciamos RabbitMQ RPC en un hilo separado
    rb_thread = threading.Thread(target=_start_rabbitmq, daemon=True)
    rb_thread.start()
