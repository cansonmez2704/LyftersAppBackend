from django.db.models import Q
from rest_framework.viewsets import ModelViewSet
from rest_framework import permissions
from .models import Exercise , Workout
from .serializers import ExerciseSerializer , WorkoutSerializer , WorkoutWriteSerializer
from common.permissions import IsOwnerOrReadOnly

class ExerciseViewSet(ModelViewSet):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    
    def get_permissions(self):
        if self.request.method != "GET":
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

class WorkoutViewSet(ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly | permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return WorkoutWriteSerializer
        return WorkoutSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)    
    
    def get_queryset(self):
        queryset = Workout.objects.select_related("owner__profile").prefetch_related("workout_exercises__exercise__muscles","workout_exercises__sets")

        if self.request.user.is_staff:
            return queryset
        
        return queryset.filter(
            Q(owner=self.request.user) | Q(visibility=Workout.Visibility.PUBLIC)
        )
    






       





