from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import WorkoutViewSet, ExerciseViewSet

# Workouts live at the root of /api/v1/workouts/ (instead of the old double
# /api/v1/workouts/workouts/). Exercises remain a nested collection.
router = DefaultRouter()
router.register(r"exercises", ExerciseViewSet, basename="exercises")

workout_list = WorkoutViewSet.as_view({"get": "list", "post": "create"})
workout_detail = WorkoutViewSet.as_view({
    "get": "retrieve",
    "put": "update",
    "patch": "partial_update",
    "delete": "destroy",
})

urlpatterns = [
    path("", workout_list, name="workouts-list"),
    path("<uuid:uuid>/", workout_detail, name="workouts-detail"),
    path("", include(router.urls)),
]
