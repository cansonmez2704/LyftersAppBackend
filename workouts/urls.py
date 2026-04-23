from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import WorkoutViewSet, ExerciseViewSet

router = DefaultRouter()

# 1. Register Exercises as a sub-collection
# URL: /api/v1/workouts/exercises/
router.register(r"exercises", ExerciseViewSet, basename="exercises")

# 2. Register Workouts at the ROOT of the router
# URL: /api/v1/workouts/
router.register(r"", WorkoutViewSet, basename="workout")

urlpatterns = [
    # Include the router URLs directly
    path("", include(router.urls)),
]