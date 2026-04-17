from django.db.models import Q
from rest_framework.viewsets import ModelViewSet
from rest_framework import permissions

from .models import Exercise, Workout
from .serializers import (
    ExerciseSerializer,
    WorkoutSerializer,
    WorkoutWriteSerializer,
    WorkoutListSerializer,
)
from common.permissions import IsOwnerOrReadOnly


class ExerciseViewSet(ModelViewSet):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    lookup_field = "uuid"

    def get_permissions(self):
        if self.request.method != "GET":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]


class WorkoutViewSet(ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly | permissions.IsAdminUser]
    lookup_field = "uuid"

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return WorkoutWriteSerializer
        if self.action == 'list':
            return WorkoutListSerializer
        return WorkoutSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def get_queryset(self):
        queryset = Workout.objects.select_related("owner__profile")

        # Only pull the exercise/set/muscle tree when the detail view needs it.
        # List views get the minimal serializer above, so this prefetch would
        # be ~2400 related rows per request on a power user's workout list.
        if self.action in ('retrieve', 'update', 'partial_update'):
            queryset = queryset.prefetch_related(
                "workout_exercises__exercise__muscles",
                "workout_exercises__sets",
            )

        if self.request.user.is_staff:
            return queryset

        return queryset.filter(
            Q(owner=self.request.user) | Q(visibility=Workout.Visibility.PUBLIC)
        )
