from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .notifications import send_cierre_materia
from .importers import import_materias_from_pdf, import_materias_from_text
from .models import Periodo, Materia
from .pagination import APIPageNumberPagination
from .serializers import PeriodoSerializer, MateriaSerializer, MateriaImportSerializer
from rest_framework.permissions import IsAuthenticated, BasePermission


def _user_role(user):
    if not user:
        return None
    if hasattr(user, "get"):
        return user.get("rol")
    return getattr(user, "rol", None)


class IsDocente(BasePermission):
    """Permite acceso solo a usuarios con rol Docente o Administrador."""
    def has_permission(self, request, view):
        return _user_role(request.user) in {"Docente", "Administrador", "ADMIN"}

class IsAdminOrDocente(BasePermission):
    def has_permission(self, request, view):
        return _user_role(request.user) in {"Administrador", "Docente", "ADMIN"}


class PeriodoViewSet(viewsets.ModelViewSet):
    queryset = Periodo.objects.all()
    serializer_class = PeriodoSerializer
    pagination_class = APIPageNumberPagination
    permission_classes = [IsAuthenticated, IsAdminOrDocente]

    def get_queryset(self):
        queryset = super().get_queryset()
        activo = self.request.query_params.get("activo")
        if activo is not None:
            queryset = queryset.filter(activo=activo.lower() in {"1", "true", "yes"})
        return queryset

    def _success(self, data=None, message="Operación completada correctamente.", code=status.HTTP_200_OK):
        return Response({"success": True, "data": data, "message": message}, status=code)

    def _error(self, message, code):
        return Response({"success": False, "data": None, "message": message}, status=code)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return self._success(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return self._success(serializer.data, "Periodo creado correctamente.", status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self._success(self.get_serializer(instance).data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return self._success(serializer.data, "Periodo actualizado correctamente.")

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return self._success(None, "Periodo eliminado correctamente.")

    @action(detail=False, methods=["get"], url_path="activo")
    def activo(self, request):
        periodo = Periodo.objects.filter(activo=True).first()
        if not periodo:
            return self._error("No existe un periodo activo.", status.HTTP_404_NOT_FOUND)
        return self._success(self.get_serializer(periodo).data, "Periodo activo encontrado.")

    @action(detail=True, methods=["post"], url_path="activar")
    def activar(self, request, pk=None):
        periodo = self.get_object()
        periodo.activo = True
        periodo.save()
        return self._success(self.get_serializer(periodo).data, "Periodo activado correctamente.")


class MateriaViewSet(viewsets.ModelViewSet):
    queryset = Materia.objects.all()
    serializer_class = MateriaSerializer
    pagination_class = APIPageNumberPagination
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        periodo_id = params.get("periodo_id")
        docente_id = params.get("docente_id")
        search = params.get("search")
        activo = params.get("activo")

        if periodo_id:
            queryset = queryset.filter(periodo_id=periodo_id)
        if docente_id:
            queryset = queryset.filter(docente_id=docente_id)
        if search:
            queryset = queryset.filter(Q(nombre__icontains=search) | Q(nrc__icontains=search))
        if activo is not None:
            queryset = queryset.filter(activo=activo.lower() in {"1", "true", "yes"})
        return queryset

    def _success(self, data=None, message="Operación completada correctamente.", code=status.HTTP_200_OK):
        return Response({"success": True, "data": data, "message": message}, status=code)

    def _error(self, message, code):
        return Response({"success": False, "data": None, "message": message}, status=code)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return self._success(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return self._success(serializer.data, "Materia creada correctamente.", status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self._success(self.get_serializer(instance).data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return self._success(serializer.data, "Materia actualizada correctamente.")

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return self._success(None, "Materia eliminada correctamente.")

    @action(detail=False, methods=["post"], url_path="importar", permission_classes=[IsAuthenticated, IsAdminOrDocente])
    def importar(self, request):
        serializer = MateriaImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        periodo_id = serializer.validated_data["periodo_id"]
        archivo = serializer.validated_data.get("archivo")
        texto = serializer.validated_data.get("texto", "").strip()

        try:
            if archivo is not None:
                result = import_materias_from_pdf(
                    archivo,
                    periodo_id=periodo_id,
                )
            else:
                result = import_materias_from_text(
                    texto,
                    periodo_id=periodo_id,
                )
        except ValueError as exc:
            return self._error(str(exc), status.HTTP_400_BAD_REQUEST)

        return self._success(
            {
                "periodo_id": periodo_id,
                **result,
            },
            "Importación de materias completada correctamente.",
            status.HTTP_201_CREATED if result["created"] else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="cerrar",
        permission_classes=[IsAuthenticated, IsAdminOrDocente])
    def cerrar(self, request, pk=None):
        materia = self.get_object()
        materia.activo = False
        materia.save()

        # Extraer token de autorización
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header else 'no-token'

        try:
            notified = send_cierre_materia(
                materia_id=materia.id,
                materia_nombre=materia.nombre,
                nrc=materia.nrc,
                auth_token=token
            )
        except Exception as exc:
            return self._error(f"No se pudo notificar el cierre de la materia: {str(exc)}", status.HTTP_502_BAD_GATEWAY)

        if not notified:
            return self._error("El servicio de notificaciones rechazó el cierre de la materia.", status.HTTP_502_BAD_GATEWAY)

        return self._success(
            self.get_serializer(materia).data,
            "Materia cerrada y notificación enviada correctamente.",
        )


    @action(detail=False, methods=["get"], url_path="por-periodo/(?P<periodo_id>[^/.]+)")
    def por_periodo(self, request, periodo_id=None):
        materias = self.get_queryset().filter(periodo_id=periodo_id)
        serializer = self.get_serializer(materias, many=True)
        return self._success(serializer.data, f"Materias del periodo {periodo_id}.")

    @action(detail=False, methods=["get"], url_path="con-periodo")
    def con_periodo(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        periodo_ids = list(queryset.values_list("periodo_id", flat=True).distinct())
        periodos_cache = {p.id: p.nombre for p in Periodo.objects.filter(id__in=periodo_ids)}
        data = []

        for materia in queryset:
            item = self.get_serializer(materia).data
            item["periodo_nombre"] = periodos_cache.get(materia.periodo_id, "")
            data.append(item)

        return self._success(data, "Materias con nombre de periodo obtenidas correctamente.")

