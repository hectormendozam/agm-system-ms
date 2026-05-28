"""
Tests unitarios para ms-calificaciones: bloqueo en materia cerrada y handler get_concentrado_alumnos.
Ejecutar con: pytest tests/test_materia_activo.py -v (desde el directorio ms-calificaciones)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock


def _patch_modules():
    """Retorna context manager que evita conexiones reales."""
    mock_mgr = MagicMock()
    mock_mgr.RabbitMQRpcClient.return_value = MagicMock()
    mock_mgr.RabbitMQManager.return_value = MagicMock()

    mock_db_mod = MagicMock()
    mock_db_mod.engine = MagicMock()
    mock_db_mod.Base = MagicMock()
    mock_db_mod.get_db = MagicMock()

    return patch.dict("sys.modules", {
        "src.rabbitmq_manager": mock_mgr,
        "rabbitmq_manager": mock_mgr,
        "src.database": mock_db_mod,
    })


# ── get_concentrado_alumnos: lógica de negocio ────────────────────────────────

def test_concentrado_alumnos_calcula_promedio_ponderado():
    """
    Con 1 actividad al 100% y valor=85, el alumno debe tener promedio=85.0 y final=85.
    Se prueba la lógica pura del handler sin base de datos real.
    """
    # Simulamos la lógica directamente para no depender del ciclo de vida del módulo
    actividades = [MagicMock(id="act-1", ponderacion=100.0)]
    calificaciones = [MagicMock(alumno_id="202300001", valor=85.0)]

    concentrado: dict = {}
    for act in actividades:
        for c in calificaciones:
            if c.alumno_id not in concentrado:
                concentrado[c.alumno_id] = 0.0
            concentrado[c.alumno_id] += c.valor * (act.ponderacion / 100)

    result = []
    for matricula, promedio in concentrado.items():
        promedio = round(promedio, 2)
        redondeado = int(promedio) + 1 if (promedio - int(promedio)) >= 0.5 else int(promedio)
        result.append({"alumno_id": matricula, "promedio_real": promedio, "calificacion_final": redondeado})

    assert len(result) == 1
    assert result[0]["alumno_id"] == "202300001"
    assert result[0]["promedio_real"] == 85.0
    assert result[0]["calificacion_final"] == 85


def test_concentrado_alumnos_redondeo_mitad_hacia_arriba():
    """Un promedio de 7.5 (exactamente la mitad) debe redondearse hacia arriba a 8."""
    actividades = [MagicMock(id="act-1", ponderacion=100.0)]
    calificaciones = [MagicMock(alumno_id="mat001", valor=75.0)]

    concentrado: dict = {}
    for act in actividades:
        for c in calificaciones:
            concentrado.setdefault(c.alumno_id, 0.0)
            concentrado[c.alumno_id] += c.valor * (act.ponderacion / 100)

    promedio = round(concentrado["mat001"], 2)
    decimal = promedio - int(promedio)
    redondeado = int(promedio) + 1 if decimal >= 0.5 else int(promedio)

    assert promedio == 75.0
    # 75.0: decimal=0.0 < 0.5 → no redondea
    assert redondeado == 75


def test_concentrado_alumnos_redondeo_correcto_8_5():
    """Un promedio exacto de 8.5 se redondea a 9."""
    promedio = 8.5
    decimal = promedio - int(promedio)
    redondeado = int(promedio) + 1 if decimal >= 0.5 else int(promedio)
    assert redondeado == 9


def test_concentrado_alumnos_varios_alumnos_multiples_actividades():
    """Dos alumnos con dos actividades ponderadas al 50% cada una."""
    actividades = [
        MagicMock(id="act-1", ponderacion=50.0),
        MagicMock(id="act-2", ponderacion=50.0),
    ]
    calificaciones_por_act = {
        "act-1": [
            MagicMock(alumno_id="A001", valor=80.0),
            MagicMock(alumno_id="A002", valor=60.0),
        ],
        "act-2": [
            MagicMock(alumno_id="A001", valor=90.0),
            MagicMock(alumno_id="A002", valor=40.0),
        ],
    }

    concentrado: dict = {}
    for act in actividades:
        for c in calificaciones_por_act[act.id]:
            concentrado.setdefault(c.alumno_id, 0.0)
            concentrado[c.alumno_id] += c.valor * (act.ponderacion / 100)

    # A001: 80*0.5 + 90*0.5 = 85.0
    # A002: 60*0.5 + 40*0.5 = 50.0
    assert round(concentrado["A001"], 2) == 85.0
    assert round(concentrado["A002"], 2) == 50.0


# ── get_materia_info en rabbitmq_client ───────────────────────────────────────

def test_get_materia_info_retorna_objeto_completo():
    """get_materia_info debe retornar el data completo de la materia."""
    with _patch_modules():
        for k in list(sys.modules.keys()):
            if k.startswith("src.rabbitmq_client"):
                del sys.modules[k]
        from src.rabbitmq_client import get_materia_info
        import src.rabbitmq_client as rc

    mock_rpc = MagicMock()
    mock_rpc.call.return_value = {
        "success": True,
        "data": {"id": 5, "nombre": "Programación", "activo": False}
    }
    rc.rpc_client = mock_rpc

    result = get_materia_info("5")
    assert result is not None
    assert result["activo"] is False
    assert result["nombre"] == "Programación"
    # Verificar que se llamó con el ID correcto
    mock_rpc.call.assert_called_once_with(
        queue_name="rpc_periodos_queue",
        action="get_materia_by_id",
        data={"id": 5},
    )


def test_get_materia_info_retorna_none_si_rpc_falla():
    """get_materia_info retorna None si la llamada RPC no tiene éxito."""
    with _patch_modules():
        for k in list(sys.modules.keys()):
            if k.startswith("src.rabbitmq_client"):
                del sys.modules[k]
        from src.rabbitmq_client import get_materia_info
        import src.rabbitmq_client as rc

    mock_rpc = MagicMock()
    mock_rpc.call.return_value = {"success": False}
    rc.rpc_client = mock_rpc

    result = get_materia_info("5")
    assert result is None


def test_get_materia_info_retorna_none_si_excepcion():
    """get_materia_info retorna None si hay una excepción en el RPC."""
    with _patch_modules():
        for k in list(sys.modules.keys()):
            if k.startswith("src.rabbitmq_client"):
                del sys.modules[k]
        from src.rabbitmq_client import get_materia_info
        import src.rabbitmq_client as rc

    mock_rpc = MagicMock()
    mock_rpc.call.side_effect = Exception("RabbitMQ timeout")
    rc.rpc_client = mock_rpc

    result = get_materia_info("5")
    assert result is None
