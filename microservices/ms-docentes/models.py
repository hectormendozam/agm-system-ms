"""
models.py – Entidades de la base de datos del MS-3: Docentes & Alumnos
Cada tabla pertenece a la base de datos independiente: agm_docentes_db
"""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base


class Docente(Base):
    """
    Directorio docente importado desde el PDF oficial de programación académica.
    Campos indexados para búsquedas rápidas por nombre, NRC y clave de materia.
    """
    __tablename__ = "docentes"

    id          = Column(Integer, primary_key=True, index=True)
    nombre      = Column(String(200), nullable=False, index=True)
    email       = Column(String(200), unique=True, nullable=True, index=True)
    departamento = Column(String(200), nullable=True)
    activo      = Column(Boolean, default=True, nullable=False)
    # Relación 1-a-muchos: un docente imparte varias materias
    materias    = relationship("MateriaDocente", back_populates="docente")


class MateriaDocente(Base):
    """
    Materias impartidas por un docente (extraídas del PDF académico).
    Un docente puede aparecer con varios NRC/materias en el mismo PDF.
    """
    __tablename__ = "materias_docente"

    id          = Column(Integer, primary_key=True, index=True)
    docente_id  = Column(Integer, ForeignKey("docentes.id"), nullable=False)
    nrc         = Column(String(20), nullable=False, index=True)   # búsquedas por NRC
    nombre_materia = Column(String(200), nullable=False)
    seccion     = Column(String(10), nullable=True)
    clave       = Column(String(20), nullable=True)
    horario     = Column(String(100), nullable=True)

    docente     = relationship("Docente", back_populates="materias")

    __table_args__ = (
        UniqueConstraint("docente_id", "nrc", name="uq_docente_nrc"),
    )


class Alumno(Base):
    """
    Alumnos inscritos por materia, importados desde PDF.
    matrícula + nrc es la clave de negocio; se indexan ambos.
    """
    __tablename__ = "alumnos"

    id          = Column(Integer, primary_key=True, index=True)
    numero_registro = Column(Integer, nullable=True)
    matricula   = Column(String(20), nullable=False, index=True)   # búsquedas por matrícula
    nombre      = Column(String(200), nullable=False)
    email       = Column(String(200), nullable=True)
    nrc         = Column(String(20), nullable=False, index=True)   # materia a la que está inscrito
    activo      = Column(Boolean, default=True, nullable=False)    # False = baja de materia

    __table_args__ = (
        UniqueConstraint("matricula", "nrc", name="uq_matricula_nrc"),
    )
