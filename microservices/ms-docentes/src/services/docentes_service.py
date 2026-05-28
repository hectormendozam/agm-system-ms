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
from fastapi import HTTPException

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
    return bool(re.fullmatch(r"[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s\-\.,]+", texto))


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


def importar_docentes_desde_pdf(contenido: bytes, db: Session) -> int:
    """
    Procesa el PDF de programación académica y persiste los datos en PostgreSQL.
    Estrategia: upsert por nombre normalizado de docente + NRC para evitar
    duplicados en reimportaciones y para emparejar con docentes ya existentes
    importados desde el directorio (que tienen nombre con acentos/formato distinto).

    Returns:
        Número de registros de materias importados.
    """
    registros_importados = 0

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

    # Pre-cargar todos los docentes para comparación normalizada (igual que en importar_directorio)
    todos_docentes = db.query(models.Docente).all()
    docentes_map: dict[str, models.Docente] = {_normalizar_nombre(d.nombre): d for d in todos_docentes}

    for fila in agrupados.values():
        nombre_docente = fila["docente_nombre"]
        if not nombre_docente:
            continue

        # 1. Buscar el docente por nombre normalizado para emparejar con registros del directorio
        nombre_norm = _normalizar_nombre(nombre_docente)
        docente = docentes_map.get(nombre_norm)

        if not docente:
            # No existe: crear nuevo docente con el nombre tal como viene del PDF
            docente = models.Docente(nombre=nombre_docente, activo=True)
            db.add(docente)
            db.flush()
            docentes_map[nombre_norm] = docente
        else:
            docente.activo = True

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
            registros_importados += 1
        else:
            materia.nombre_materia = fila["nombre_materia"]
            materia.horario = " ; ".join(fila["horarios"])

    db.commit()
    return registros_importados


def listar_docentes(db: Session) -> List[models.Docente]:
    """Devuelve todos los docentes con sus materias (eager load automático)."""
    return db.query(models.Docente).filter(models.Docente.activo == True).all()


def buscar_docentes(db: Session, search: str | None = None) -> List[models.Docente]:
    query = db.query(models.Docente).filter(models.Docente.activo == True)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (models.Docente.nombre.ilike(like))
            | (models.Docente.email.ilike(like))
            | (models.Docente.departamento.ilike(like))
        )
    return query.order_by(models.Docente.nombre).all()


def dar_de_baja_docente(docente_id: int, db: Session) -> models.Docente:
    docente = db.query(models.Docente).filter(models.Docente.id == docente_id).first()
    if not docente:
        raise HTTPException(status_code=404, detail=f"Docente {docente_id} no encontrado")
    if not docente.activo:
        raise HTTPException(status_code=409, detail="El docente ya esta dado de baja")

    docente.activo = False
    db.commit()
    db.refresh(docente)
    return docente


import unicodedata

def _normalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre para comparación tolerante a OCR.
    Quita acentos, guiones, espacios y cualquier carácter no-letra.
    Así 'M ENDEZ', 'MENDEZ' y 'Méndez' producen 'mendez'."""
    if not nombre:
        return ""
    # Quitar acentos/diacríticos
    s = ''.join(c for c in unicodedata.normalize('NFD', nombre)
               if unicodedata.category(c) != 'Mn')
    # Dejar solo letras y pasar a minúsculas (elimina espacios, guiones, puntuación)
    s = re.sub(r'[^a-zA-Z]', '', s).lower()
    return s

def _parsear_pagina_directorio(pagina) -> List[dict]:
    """
    Extrae texto de una página del PDF "Personal Docente" y lo parsea línea por línea.
    """
    registros = []
    texto = pagina.extract_text()
    if not texto:
        return registros
    
    lineas = texto.split('\n')
    # El encabezado puede no estar en todas las páginas, así que somos más flexibles
    
    for line in lineas:
        line = line.strip()
        if not line:
            continue
            
        # Omitir líneas que son claramente encabezados o migas de pan
        if any(h in line for h in ["Nombre Correo", "Ubicación:", "Extensión:", "Página", "Directorio", "Inicio >"]):
            continue
        
        # Parsear con regex: Nombre + Email + Resto (Ubicación/Extensión)
        # El nombre suele ser varias palabras, luego un espacio y un email.
        match = re.search(r'^(.+?)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*(.*)$', line)
        if match:
            nombre = match.group(1).strip()
            email = match.group(2).strip()
            rest = match.group(3).strip()
            
            # Limpiar el nombre de posibles ruidos al inicio (como viñetas ■)
            nombre = re.sub(r'^[■\s>]+', '', nombre).strip()
            
            if len(nombre) < 3:
                continue

            ubicacion = rest.split()[0] if rest else ""
            
            registros.append({
                "nombre": nombre,
                "email": email,
                "ubicacion": ubicacion
            })
            
    return registros

def importar_directorio_docentes_pdf(contenido: bytes, db: Session) -> int:
    """
    Procesa el PDF de "Personal Docente" para actualizar/crear la información de los docentes
    (email y departamento/ubicación).
    
    Returns:
        Número de registros de docentes importados/actualizados.
    """
    registros_importados = 0

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
        nombre_norm = _normalizar_nombre(nombre_docente)

        # 1. Buscar el docente usando el nombre normalizado
        docente = docentes_map.get(nombre_norm)
        
        if not docente:
            docente = models.Docente(
                nombre=nombre_docente,
                email=email,
                departamento=fila["ubicacion"],
                activo=True,
            )
            db.add(docente)
            db.flush()
            # Actualizar el mapa por si el mismo docente aparece de nuevo
            docentes_map[nombre_norm] = docente
            registros_importados += 1
        else:
            docente.activo = True
            # Actualiza datos si ya existía y si trajo nueva información
            if email:
                docente.email = email
            if fila["ubicacion"]:
                docente.departamento = fila["ubicacion"]
            registros_importados += 1

    db.commit()
    return registros_importados
