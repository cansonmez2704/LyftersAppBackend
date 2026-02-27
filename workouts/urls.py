from django.urls import path , include
from rest_framework.routers import DefaultRouter
from .views import WorkoutViewSet , ExerciseViewSet

router = DefaultRouter()
router.register(r"workouts",WorkoutViewSet,basename="workouts")
router.register(r"exercises",ExerciseViewSet,basename="exercises")

urlpatterns = [
    path("",include(router.urls)),
    
]



