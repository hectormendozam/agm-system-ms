"""
services/docentes_service.py
Lógica de negocio para importación y consulta de docentes.
Separada del controlador para mantener la responsabilidad única.
"""
import pdfplumber
from io import BytesIO
import re
import logging
from typing import List
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)


def _es_bloque_inicio(linea: str) -> bool:
    return bool(re.match(r"^\d{5}\s+", linea or ""))


def _es_salon(token: str) -> bool:
    token = token.strip()
    if not token:
        return False
    if token.upper() == "ASIGNAR":
        return True
    return any(ch.isdigit() for ch in token) and "/" in token


def _limpiar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def _recortar_ruido(texto: str) -> str:
    texto = _limpiar_texto(texto)
    if not texto:
        return ""
    for patron in ("MATERIA CRUZADA", "CON NRC"):
        indice = texto.upper().find(patron)
        if indice != -1:
            texto = texto[:indice].strip()
    return _limpiar_texto(texto)


def _es_seccion(token: str) -> bool:
    return bool(re.fullmatch(r"(?:OO\d+|\d{3})", token or ""))


def _es_dia(token: str) -> bool:
    return token in {"L", "M", "A", "J", "V", "S"}


def _es_hora(token: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{4}", token or ""))


def _es_linea_docente(texto: str) -> bool:
    texto = _recortar_ruido(texto)
    if not texto:
        return False
    if any(ch.isdigit() for ch in texto):
        return False
    if "/" in texto:
        return False
    if "CON NRC" in texto.upper() or "MATERIA CRUZADA" in texto.upper():
        return False
    return bool(re.fullmatch(r"[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s\-\.]+", texto))


def _extraer_docente_y_salon(resto: str, extras: List[str]) -> tuple[str, str]:
    docente_partes: List[str] = []
    salon = ""

    texto = _recortar_ruido(resto)
    if texto:
        tokens = texto.split()
        indice_salon = next(
            (i for i, token in enumerate(tokens) if _es_salon(token)),
            None,
        )
        if indice_salon is None:
            docente_partes.append(texto)
        else:
            docente_fragmento = _limpiar_texto(" ".join(tokens[:indice_salon]))
            if docente_fragmento:
                docente_partes.append(docente_fragmento)
            salon_fragmento = _limpiar_texto(" ".join(tokens[indice_salon:]))
            if salon_fragmento:
                salon = salon_fragmento

    for linea in extras:
        texto_original = _limpiar_texto(linea)
        if not texto_original:
            continue
        if "MATERIA CRUZADA" in texto_original.upper():
            continue

        texto = _recortar_ruido(texto_original)
        if not texto:
            continue

        if _es_linea_docente(texto):
            docente_partes.append(texto)
            continue

        tokens = texto.split()
        indice_salon = next(
            (i for i, token in enumerate(tokens) if _es_salon(token)),
            None,
        )
        if indice_salon is not None:
            if not salon:
                salon = _limpiar_texto(" ".join(tokens[indice_salon:]))
            docente_fragmento = _limpiar_texto(" ".join(tokens[:indice_salon]))
            if docente_fragmento and _es_linea_docente(docente_fragmento):
                docente_partes.append(docente_fragmento)

    docente = _limpiar_texto(" ".join(docente_partes))
    salon = _limpiar_texto(salon)
    return docente, salon


def _parsear_linea_materia(linea: str) -> dict | None:
    """
    Convierte una línea de programación académica en una fila estructurada.
    Formato esperado:
      NRC CLAVE MATERIA SECCION DIA HORA [DOCENTE...] [SALON...]
    """
    tokens = _limpiar_texto(linea).split()
    if len(tokens) < 7:
        return None
    if not tokens[0].isdigit() or len(tokens[0]) != 5:
        return None

    idx = 1
    if idx + 1 >= len(tokens):
        return None

    if not tokens[idx].isalpha() or not re.fullmatch(r"\d{3}", tokens[idx + 1]):
        return None

    clave = f"{tokens[idx]} {tokens[idx + 1]}"
    idx += 2

    try:
        seccion_idx = next(i for i in range(idx, len(tokens)) if _es_seccion(tokens[i]))
    except StopIteration:
        return None

    nombre_materia = _limpiar_texto(" ".join(tokens[idx:seccion_idx]))
    if not nombre_materia:
        return None

    if seccion_idx + 2 >= len(tokens):
        return None

    dia = tokens[seccion_idx + 1]
    hora = tokens[seccion_idx + 2]
    if not _es_dia(dia) or not _es_hora(hora):
        return None

    resto = " ".join(tokens[seccion_idx + 3:])
    return {
        "nrc": tokens[0],
        "clave": clave,
        "nombre_materia": nombre_materia,
        "seccion": tokens[seccion_idx],
        "dia": dia,
        "hora": hora,
        "resto": resto,
        "extras": [],
    }


def _parsear_pagina(pagina) -> List[dict]:
    """
    Parsea una página del PDF oficial BUAP usando líneas de texto.
    El formato real suele ser:
      NRC Clave Materia Secc Día Hora
      [líneas con el nombre del profesor]
      [línea con el salón]
    """
    texto = pagina.extract_text() or ""
    lineas = [linea.strip() for linea in texto.split("\n") if linea.strip()]

    registros = []
    registro_actual = None

    for linea in lineas:
        linea_normalizada = _limpiar_texto(linea)
        if registro_actual and (
            "MATERIA CRUZADA" in linea_normalizada.upper()
            or "CON NRC" in linea_normalizada.upper()
        ):
            registros.extend(_finalizar_registro(registro_actual))
            registro_actual = None
            continue

        posible_registro = _parsear_linea_materia(linea)
        if posible_registro:
            if registro_actual:
                registros.extend(_finalizar_registro(registro_actual))
            registro_actual = posible_registro
            continue

        if registro_actual:
            registro_actual["extras"].append(linea)

    if registro_actual:
        registros.extend(_finalizar_registro(registro_actual))

    return registros


def _finalizar_registro(registro: dict) -> List[dict]:
    docente_nombre, salon = _extraer_docente_y_salon(
        registro.get("resto", ""),
        registro.get("extras", []),
    )

    if not docente_nombre:
        logger.warning(
            "No se pudo detectar docente para NRC %s (%s)",
            registro.get("nrc"),
            registro.get("nombre_materia"),
        )
        return []

    if len(docente_nombre) > 200:
        logger.warning(
            "Docente demasiado largo para NRC %s, se truncará: %s",
            registro.get("nrc"),
            docente_nombre,
        )
        docente_nombre = docente_nombre[:200].strip()

    if docente_nombre and " " not in docente_nombre and not registro.get("extras"):
        logger.warning(
            "Docente muy corto o incompleto para NRC %s: %s",
            registro.get("nrc"),
            docente_nombre,
        )

    return [
        {
            "nrc": registro["nrc"],
            "clave": registro["clave"],
            "nombre_materia": registro["nombre_materia"],
            "seccion": registro["seccion"],
            "docente_nombre": docente_nombre,
            "horario": f"{registro['dia']} {registro['hora']}",
            "salon": salon,
        }
    ]


def importar_docentes_desde_pdf(contenido: bytes, db: Session) -> List[models.Docente]:
    """
    Procesa el PDF de programación académica y persiste los datos en PostgreSQL.
    Estrategia: upsert por nombre de docente + NRC para evitar duplicados en
    reimportaciones.

    Returns:
        Lista de docentes procesados.
    """
    docentes_procesados = []

    with pdfplumber.open(BytesIO(contenido)) as pdf:
        filas = []
        for pagina in pdf.pages:
            filas.extend(_parsear_pagina(pagina))

    agrupados: dict[tuple[str, str, str, str, str], dict] = {}
    for fila in filas:
        llave = (
            fila["nrc"],
            fila["clave"],
            fila["nombre_materia"],
            fila["seccion"],
            fila["docente_nombre"],
        )
        registro = agrupados.setdefault(
            llave,
            {
                "nrc": fila["nrc"],
                "clave": fila["clave"],
                "nombre_materia": fila["nombre_materia"],
                "seccion": fila["seccion"],
                "docente_nombre": fila["docente_nombre"],
                "horarios": [],
            },
        )
        if fila["horario"] not in registro["horarios"]:
            registro["horarios"].append(fila["horario"])

    # Pre-cargar docentes existentes para comparación normalizada
    todos_docentes = db.query(models.Docente).all()
    docentes_map = {_normalizar_nombre(d.nombre): d for d in todos_docentes}

    for fila in agrupados.values():
        nombre_docente = fila["docente_nombre"]
        if not nombre_docente:
            continue

        nombre_norm = _normalizar_nombre(nombre_docente)

        # 1. Buscar o crear el docente en ms-docentes
        docente = docentes_map.get(nombre_norm)
        
        if not docente:
            docente = models.Docente(nombre=nombre_docente)
            db.add(docente)
            db.flush()   # obtenemos el id sin hacer commit todavía
            
            # 1.1 Registrar en Auth con email genérico o temporal si no lo tiene aún
            username_part = re.sub(r'[^a-z0-9]', '', nombre_docente.lower())[:20]
            temp_email = f"{username_part}@docente.buap.mx"
            temp_clave = "password123"
            
            rpc_client.call('rpc_auth_queue', 'create_user', {
                "email": temp_email,
                "password": temp_clave,
                "rol": "Docente"
            })
            
            docentes_map[nombre_norm] = docente
        if docente not in docentes_procesados:
            docentes_procesados.append(docente)

        # 2. Upsert de la materia del docente
        materia = (
            db.query(models.MateriaDocente)
            .filter(
                models.MateriaDocente.docente_id == docente.id,
                models.MateriaDocente.nrc == fila["nrc"],
            )
            .first()
        )
        if not materia:
            materia = models.MateriaDocente(
                docente_id=docente.id,
                nrc=fila["nrc"],
                nombre_materia=fila["nombre_materia"],
                seccion=fila["seccion"],
                clave=fila["clave"],
                horario=" ; ".join(fila["horarios"]),
            )
            db.add(materia)
        else:
            # Actualiza datos si ya existía
            materia.nombre_materia = fila["nombre_materia"]
            materia.horario = " ; ".join(fila["horarios"])

    db.commit()
    for d in docentes_procesados:
        db.refresh(d)
    return docentes_procesados


def listar_docentes(db: Session) -> List[models.Docente]:
    """Devuelve todos los docentes con sus materias (eager load automático)."""
    return db.query(models.Docente).all()


def buscar_docentes(db: Session, search: str | None = None) -> List[models.Docente]:
    query = db.query(models.Docente)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (models.Docente.nombre.ilike(like))
            | (models.Docente.email.ilike(like))
            | (models.Docente.departamento.ilike(like))
        )
    return query.order_by(models.Docente.nombre).all()


# ── Importación del Directorio "Personal Docente" ─────────────────────────────
def _parsear_pagina_directorio(pagina) -> List[dict]:
    """
    Extrae texto de una página del PDF "Personal Docente" y lo parsea línea por línea.
    """
    registros = []
    texto = pagina.extract_text()
    if not texto:
        return registros
    
    lineas = texto.split('\n')
    started = False
    
    for line in lineas:
        line = line.strip()
        if not line:
            continue
        # Buscar el encabezado para empezar a parsear (o seguir si ya empezó)
        if "Nombre Correo" in line:
            started = True
            continue
        if not started:
            continue
        
        # Parsear con regex
        match = re.search(r'^(.*?)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*(.*)$', line)
        if match:
            nombre = match.group(1).strip()
            email = match.group(2).strip()
            rest = match.group(3).strip()
            ubicacion = rest.split()[0] if rest else ""
            
            registros.append({
                "nombre": nombre,
                "email": email,
                "ubicacion": ubicacion
            })
            
    return registros

from rabbitmq_manager import RabbitMQRpcClient
import secrets
import string

def _generar_clave_unica(length=8) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for i in range(length))

import unicodedata

def _normalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre: quita acentos, convierte a minúsculas y limpia espacios/puntuación."""
    if not nombre:
        return ""
    # Quitar acentos
    s = ''.join(c for c in unicodedata.normalize('NFD', nombre)
               if unicodedata.category(c) != 'Mn')
    # Quitar guiones y puntuación, pasar a minúsculas
    s = re.sub(r'[^a-zA-Z\s]', ' ', s).lower()
    # Limpiar espacios
    return ' '.join(s.split())

def importar_directorio_docentes_pdf(contenido: bytes, db: Session) -> int:
    """
    Procesa el PDF de "Personal Docente" para actualizar/crear la información de los docentes
    (email y departamento/ubicación) y los registra en MS-Auth.
    """
    registros_importados = 0
    rpc_client = RabbitMQRpcClient()

    with pdfplumber.open(BytesIO(contenido)) as pdf:
        filas = []
        for pagina in pdf.pages:
            filas.extend(_parsear_pagina_directorio(pagina))

    # Pre-cargar todos los docentes para comparación normalizada
    todos_docentes = db.query(models.Docente).all()
    docentes_map = {_normalizar_nombre(d.nombre): d for d in todos_docentes}

    for fila in filas:
        nombre_docente = fila["nombre"]
        if not nombre_docente:
            continue

        email = fila["email"]
        clave = "password123"
        nombre_norm = _normalizar_nombre(nombre_docente)

        # 1. Buscar el docente usando el nombre normalizado
        docente = docentes_map.get(nombre_norm)
        
        if not docente:
            docente = models.Docente(
                nombre=nombre_docente,
                email=email,
                departamento=fila["ubicacion"]
            )
            db.add(docente)
            db.flush()
            # Actualizar el mapa por si el mismo docente aparece de nuevo
            docentes_map[nombre_norm] = docente
        else:
            if email:
                docente.email = email
            if fila["ubicacion"]:
                docente.departamento = fila["ubicacion"]
        
        # 2. Registrar en Auth
        if email:
            rpc_client.call('rpc_auth_queue', 'create_user', {
                "email": email,
                "password": "password123", # Password por defecto para docentes importados
                "rol": "Docente"
            })

        registros_importados += 1

    db.commit()
    for d in docentes_procesados:
        db.refresh(d)
    return docentes_procesados
