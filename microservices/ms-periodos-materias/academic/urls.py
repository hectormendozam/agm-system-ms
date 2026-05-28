from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import PeriodoViewSet, MateriaViewSet, InternalMateriaByNrcView

router = DefaultRouter()
router.register(r"periodos", PeriodoViewSet, basename="periodos")
router.register(r"materias", MateriaViewSet, basename="materias")

urlpatterns = [
    path("", include(router.urls)),
    path("internal/materias/<str:nrc>/", InternalMateriaByNrcView.as_view()),
]
