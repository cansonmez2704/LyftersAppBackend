from django.db.models import Q
from django.contrib.postgres.search import SearchQuery, SearchRank
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

        if self.action in ('retrieve', 'update', 'partial_update'):
            queryset = queryset.prefetch_related(
                "workout_exercises__exercise__muscles",
                "workout_exercises__sets",
            )

        # Base visibility filtering
        if not self.request.user.is_staff:
            queryset = queryset.filter(
                Q(owner=self.request.user) | Q(visibility=Workout.Visibility.PUBLIC)
            )

        # ADDED: The Search Engine Integration
        search_term = self.request.query_params.get('q', None)
        if search_term:
            query = SearchQuery(search_term)
            queryset = queryset.filter(
                search_vector=query
            ).annotate(
                rank=SearchRank('search_vector', query)
            ).order_by('-rank') # Overrides default ordering to show most relevant first

        return queryset