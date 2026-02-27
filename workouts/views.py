from django.db.models import Q
from rest_framework.viewsets import ModelViewSet
from rest_framework import permissions
from .models import Exercise , Workout
from .serializers import ExerciseSerializer , WorkoutSerializer
from common.permissions import IsOwner

class ExerciseViewSet(ModelViewSet):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    
    def get_permissions(self):
        if self.request.method != "GET":
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

class WorkoutViewSet(ModelViewSet):
    queryset = Workout.objects.all()
    serializer_class = WorkoutSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner | permissions.IsAdminUser]

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)    
    
    def get_queryset(self):
        queryset = Workout.objects.select_related("owner").prefetch_related("workout_exercises__exercise__muscles")

        if self.request.user.is_staff:
            return queryset
        
        return queryset.filter(
            Q(owner=self.request.user) | Q(visibility=Workout.Visibility.PUBLIC)
        )
    






       





