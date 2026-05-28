# LLM.md — AGM System: Estado del proyecto

## Arquitectura
- **Gateway** (port 9000): siempre agrega el nombre del servicio al path interno (`/api/calificaciones/foo` → interno `/calificaciones/foo`). Cada microservicio tiene middleware que stripea su prefijo.
- **ms-auth** (port 8001): JWT, roles en UPPERCASE: `DOCENTE`, `ADMIN`, `ALUMNO`
- **ms-docentes** (port 8003): alumnos por `matricula` + `nrc`. RabbitMQ queue: `rpc_docentes_queue`
- **ms-calificaciones** (port 8004): actividades + calificaciones. RabbitMQ queue: `rpc_calificaciones_queue`
- **ms-periodos-materias** (port 8000 interno): materias/periodos. RabbitMQ queue: `rpc_periodos_queue`
- **ms-asistencias** (port 8005): sesiones QR. RabbitMQ queue: `rpc_asistencias_queue`
- **ms-reportes** (port 8007): descarga PDF/Excel. RabbitMQ queue: `rpc_reportes_queue`
- **Frontend** Angular 20 standalone + signals, en `/home/autc/Documents/agm-system-frontend`

## Cambios realizados esta sesión

### Backend

**ms-calificaciones/src/auth_middleware.py**
- Agregado `_normalize_role()` con `_ROLE_MAP` para mapear cualquier variante de rol al uppercase del JWT (`"Docente"` → `"DOCENTE"`, `"Administrador"` → `"ADMIN"`, etc.)
- Fix `require_roles` para normalizar antes de comparar → resuelve todos los 403

**ms-reportes/auth_middleware.py**
- Mismo fix de `_normalize_role()`

**ms-docentes/rabbitmq_server.py**
- Nuevo handler `get_alumno_by_matricula(data)` → busca alumno por matrícula y retorna nombre/email/nrc

**ms-calificaciones/src/rabbitmq_client.py**
- `get_materia_nrc(materia_id)` → llama `rpc_periodos_queue` / `get_materia_by_id` → retorna NRC
- `get_alumnos_por_nrc(nrc)` → llama `rpc_docentes_queue` / `get_alumnos_by_materia`
- `get_alumno_nombre(matricula)` → llama `rpc_docentes_queue` / `get_alumno_by_matricula`

**ms-calificaciones/src/main.py** (reescritura mayor)
- Strip middleware para prefijo `/calificaciones`
- `POST /ponderaciones/{materia_id}`: upsert (borra existentes → cascade a calificaciones → recrea)
- `DELETE /ponderaciones/{materia_id}`: endpoint nuevo
- Excel import: guard `if pd.isna(raw_valor): continue`
- `GET /concentrado/{materia_id}`: obtiene NRC vía RPC → alumnos inscritos → muestra 0 para no calificados. Incluye campo `nombre`.
- `GET /alumno/{matricula}`: vista del alumno, calificaciones por materia
- **Fix NaN crash** (esta conversación): `import math` + guard `math.isnan()` en concentrado y en vista alumno → resuelve `ValueError: cannot convert float NaN to integer`

### Frontend (agm-system-frontend)

**core/services/asistencias.service.ts**
- Corregidos prefijos URL: `sesiones/` → `asistencias/sesiones/`, `qr/` → `asistencias/qr/`, etc.

**core/services/reportes.service.ts**
- `estadisticas/docente/${id}` → `reportes/estadisticas/docente/${id}`

**core/services/calificaciones.service.ts**
- `deletePonderaciones(materiaId)` → `DELETE /calificaciones/ponderaciones/${materiaId}`
- `getMisCalificaciones(matricula)` → `GET /calificaciones/alumno/${matricula}`

**features/docente/calificaciones/docente-calificaciones.component.ts**
- Signal `reconfigurandoPond`, métodos `iniciarReconfiguracion()` / `cancelarReconfiguracion()`
- `Actividad.id` como `string` (UUIDs)
- Concentrado incluye columna `nombre`

**features/docente/calificaciones/docente-calificaciones.component.html**
- Form de config visible cuando `actividades().length === 0 || reconfigurandoPond()`
- Botón "Reconfigurar" en header de tabla de actividades
- Advertencia de borrado al reconfigurar
- Columna `nombre` en tabla de concentrado

**features/alumno/calificaciones/calificaciones.component.ts + .html**
- Resuelve matrícula via email → `AlumnosService.getAll` → `CalificacionesService.getMisCalificaciones`
- Vista con `mat-accordion` por materia, tabla de actividades, promedio

## Cambios recientes (vista docente — cierre y reportes)

**ms-periodos-materias/academic/views.py**
- Fix: agregado `from django.db.models import Q` (faltaba → NameError al usar `?search=`)

**ms-reportes/models.py**
- Nuevo campo `porcentaje_asistencia = Column(Float, default=0.0)` en `EstadisticaMateria`

**ms-reportes/schemas.py**
- `porcentaje_asistencia: float = 0.0` en `EstadisticaMateriaCreate` y `EstadisticaMateriaResponse`

**ms-reportes/rabbitmq_client.py**
- Nueva función `get_calificaciones_stats(materia_id)` → llama `rpc_calificaciones_queue` / `get_estadisticas_materia`

**ms-reportes/main.py**
- Migración inline en startup: `ALTER TABLE estadisticas_materia ADD COLUMN IF NOT EXISTS porcentaje_asistencia FLOAT DEFAULT 0`
- Nuevo endpoint `POST /estadisticas/auto/{materia_nrc}` (roles: Docente + Admin): auto-calcula stats desde ms-calificaciones y ms-asistencias vía RPC y guarda `EstadisticaMateria`

**core/services/docentes.service.ts**
- Fix: `getMateriasByDocente` ahora llama `GET /materias/?docente_id={id}` directo a ms-periodos-materias (correcto activo). La nota de "SHA1 incompatible" era errónea; `docente_id` es `PositiveIntegerField` numérico.

**core/services/reportes.service.ts**
- Nuevo método `autoRegistrarEstadisticas(nrc, docenteId)` → `POST /reportes/estadisticas/auto/{nrc}`

**features/docente/materias/docente-materias.component.ts**
- Guarda `docenteId` signal al resolver el docente en ngOnInit
- Inyecta `ReportesService`
- `cerrarMateria()`: después de éxito llama `autoRegistrarEstadisticas` (fire-and-forget)

## Cambios recientes (QR recovery + reportes REST fallback)

**ms-reportes/requirements.txt** — agregado `requests==2.32.3`

**docker-compose.yml** — agregado `MS_PERIODOS_URL=http://ms-periodos-materias:8000` en ms-reportes

**ms-reportes/rabbitmq_client.py**
- Nueva función `_materia_rest_by_nrc(nrc)` → `GET ms-periodos:8000/materias/?search={nrc}` como fallback HTTP directo
- `get_materia_by_nrc()` ahora intenta RPC primero, si falla llama el fallback REST → resuelve el 503 "No se pudo obtener información de la materia"

**features/docente/asistencias-qr/asistencias-qr.component.ts**
- `ngOnInit()` ahora usa `forkJoin({mats, sesion})`: carga materias y sesión activa en paralelo
- Si hay sesión activa al entrar (o volver desde otra pestaña), la recupera: setea `sesionActiva`, `scanning=true`, `form.materia_id`, reinicia polling y asistencias

**core/services/docentes.service.ts (reset-password)**
- Fix: `[(ngModel)]="selectedMateria"` en QR component → `materias.set(Array.isArray(res.mats) ? res.mats : [])`

## Cambios recientes (QR recovery app-nav + reports fallback + vista alumno)

**ms-asistencias/src/main.py**
- Nuevo endpoint `GET /sesiones/activa?docente_id={id}`: consulta DB para sesión activa del docente, verifica Redis, devuelve `{ id, sesion_id, materia_id }` o `null`
- Nuevo endpoint `GET /asistencias/alumno/{alumno_id}`: agrupa registros de asistencia por materia, calcula presentes/retardos/total/porcentaje

**ms-periodos-materias/academic/views.py + academic/urls.py**
- Nueva clase `InternalMateriaByNrcView` con `permission_classes = [AllowAny]` → `GET /api/internal/materias/{nrc}/`
- Permite llamadas internas sin auth (para fallback REST de ms-reportes)

**ms-reportes/rabbitmq_client.py**
- `_materia_rest_by_nrc` actualizado: ahora llama `/api/internal/materias/{nrc}/` (sin auth) → funciona aunque RPC falle

**Frontend (agm-system-frontend)**
- `core/services/asistencias.service.ts` — nuevo método `getMisAsistencias(alumnoId)`
- `alumno/calificaciones/calificaciones.component.ts` — inyecta `MateriasService`, forkJoin con `getAll(1,100)` para mapear materia_id → nombre
- `alumno/calificaciones/calificaciones.component.html` — muestra `mat.materia_nombre` en vez de "Materia ID: X"
- `alumno/asistencias/asistencias-alumno.component.*` — **nuevo componente** tabla de asistencia por materia
- `alumno/alumno-layout/alumno-layout.component.ts` — agrega nav item "Mis Asistencias" (icon: event_available)
- `alumno/alumno.routes.ts` — ruta `/alumno/asistencias` → `AsistenciasAlumnoComponent`

## Cambios recientes (vista alumno — QR simplificado + panel de materias)

**features/alumno/asistencia-qr/asistencia-qr.component.ts** (reescritura)
- Eliminado formulario manual (matrícula + NRC)
- Auto-resuelve alumno desde email del JWT via `AlumnosService.getAll(1, email)`
- Para cada NRC inscrito: busca la materia en ms-periodos-materias con `MateriasService.getAll(1, 10, nrc)` → obtiene `materia.id` (DB ID) y `materia.nombre`
- Si una sola materia: auto-selecciona y genera QR
- Si múltiples materias: muestra lista de botones para elegir
- `materia_id` en `generarQrToken` ahora usa el DB ID correcto (no el NRC) → Redis key `sesion_activa:{db_id}` coincide con lo que guarda el docente
- Estado `sinSesion` cuando `generarQrToken` retorna 404 → mensaje "no hay sesión activa"

**features/alumno/calificaciones/calificaciones.component.ts** (fix materia lookup)
- Ya no llama `MateriasService.getAll(1, 100)` (all-materias, poco fiable)
- Usa NRCs del alumno para buscar materias específicas por NRC → mapea `materia_id → nombre`
- `forkJoin` interno: `{ calif, materiasByNrc }` donde `materiasByNrc` es un mapa por NRC

**features/alumno/panel/** (nuevo componente)
- `PanelComponent`: muestra lista de materias inscritas del alumno
- Mismo patrón: email → alumno rows → NRCs → MateriasService por NRC
- Chip "Activa" / "Cerrada" según `materia.activo`
- Es ahora la ruta por defecto (`redirectTo: 'panel'`)

**alumno.routes.ts** — ruta `panel` agregada, default cambiado de `asistencia` → `panel`
**alumno-layout.component.ts** — nav item "Mis Materias" (icon: school, path: panel) al inicio

## Cambios recientes (fix NRC como clave de sesión QR)

**docente/asistencias-qr/asistencias-qr.component.html**
- `[value]="m.id"` → `[value]="m.nrc"`: el select de materia ahora envía el NRC (no el ID de MateriaDocente de ms-docentes)
- `track m.id` → `track m.nrc`

**alumno/asistencia-qr/asistencia-qr.component.ts** (simplificado)
- Ya no hace lookup de `Materia.id` en ms-periodos-materias
- Usa `Number(row.nrc)` directamente como `materia_id` en `generarQrToken`
- Carga nombres de materias en background para display (no bloquea el flujo)
- Eliminado signal `materiaDbIds`

**Por qué era el bug**: El docente usaba `m.id = MateriaDocente.id` (de ms-docentes, ej. 5) → Redis `sesion_activa:5`. El alumno buscaba `Materia.id` en ms-periodos-materias (ej. 58) → buscaba `sesion_activa:58`. IDs de dos bases de datos distintas → nunca coincidían.

**Fix**: Usar NRC como clave universal (`sesion_activa:{nrc}`). Todos los extremos son consistentes: docente inicia con NRC, Redis guarda `sesion_activa:{nrc}`, alumno genera QR con NRC, backend valida `sesion_activa:{nrc}`.

## Cambios recientes (fix auth logout + QR)

**ms-docentes/auth_middleware.py** (reescritura)
- Eliminada validación vía RabbitMQ RPC a ms-auth (creaba nueva conexión por request → timeout → 401 falso → logout del alumno)
- Ahora valida JWT localmente con PyJWT (mismo SECRET_KEY que ms-auth)
- Agrega `PyJWT==2.8.0` en requirements.txt

**ms-asistencias/src/auth_middleware.py** (reescritura)
- Mismo fix: elimina RPC auth, usa local JWT con PyJWT
- Elimina import de `RabbitMQRpcClient` del auth middleware
- Agrega `PyJWT==2.8.0` en requirements.txt

**Por qué**: El RPC a `rpc_auth_queue` tenía timeout de 10s. Cuando expiraba, `call()` retornaba `None`. El código anterior hacía `if not response → 401`. Esto causaba logouts del alumno al navegar a cualquier sección que llamara a ms-docentes o ms-asistencias (Mis Asistencias, calificaciones). Con validación local, el 401 solo ocurre si el JWT es genuinamente inválido/expirado.

## Problemas conocidos / pendientes

1. **NaN en DB**: Calificaciones importadas antes del fix de Excel pueden tener `NaN` en `valor`. El código ya los trata como 0, pero idealmente hacer un script SQL: `UPDATE calificacion SET valor = 0 WHERE valor != valor;` (NaN != NaN en float SQL)

2. **ms-periodos-materias cierra materia → 502 si RabbitMQ falla**: La materia SÍ se cierra en DB pero el endpoint retorna 502. Fix: cambiar los bloques `except` en `views.py` líneas 207-213 para retornar 200 con warning.

3. **Dashboard docente usa datos random**: `buildCharts()` en `docente-dashboard.component.ts` usa `Math.random()`. Debe llamar `AlumnosService.getByMateria(nrc)` via `forkJoin` para datos reales.

4. **Vista alumno — materia_id en lugar de nombre**: El panel expansion muestra `Materia ID: 58` en vez del nombre. Para mostrar el nombre hay que hacer RPC a ms-periodos-materias desde el frontend o desde el endpoint `/alumno/{matricula}`.

## Cómo reconstruir tras cambios Python
```bash
docker compose build <servicio> && docker compose up -d <servicio>
```
