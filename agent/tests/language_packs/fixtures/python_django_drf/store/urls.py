from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .views import ProductViewSet

router = DefaultRouter()
router.register(r"products", ProductViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("health/", views.health_check),
]
