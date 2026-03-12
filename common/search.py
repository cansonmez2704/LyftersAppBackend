"""
Global search endpoint — queries UserProfiles, Exercises, and Workouts
using PostgreSQL Full-Text Search (SearchRank) with a Trigram Similarity
fallback for typo-tolerant, weighted-ranking search.
"""

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramSimilarity
from django.db.models import Q, FloatField
from django.db.models.functions import Greatest

from rest_framework import serializers, status
from rest_framework.throttling import UserRateThrottle
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import UserProfile
from users.serializers import MiniUserProfileSerializer
from workouts.models import Exercise, Workout



class UserSearchResultSerializer(serializers.ModelSerializer):
    """Minimal user result: uuid, username, avatar."""
    username = serializers.CharField(source="user.username")
    uuid = serializers.UUIDField(source="user.uuid")
    rank = serializers.FloatField(read_only=True)

    class Meta:
        model = UserProfile
        fields = ("uuid", "username", "avatar", "bio", "rank")


class ExerciseSearchResultSerializer(serializers.ModelSerializer):
    muscles = serializers.StringRelatedField(many=True)
    rank = serializers.FloatField(read_only=True)

    class Meta:
        model = Exercise
        fields = ("id", "name", "exercise_type", "movement_type", "muscles", "rank")


class WorkoutSearchResultSerializer(serializers.ModelSerializer):
    owner = MiniUserProfileSerializer(source="owner.profile", read_only=True)
    rank = serializers.FloatField(read_only=True)

    class Meta:
        model = Workout
        fields = ("id", "name", "description", "owner", "rank")


# ---------------------------------------------------------------------------
# Hybrid search helper
# ---------------------------------------------------------------------------

SIMILARITY_THRESHOLD = 0.15
FTS_THRESHOLD = 0.05
RESULTS_PER_TYPE = 10


def _hybrid_search(queryset, term, search_fields_for_trigram):
    """Run FTS (SearchRank) on the pre-built search_vector, then enrich
    with TrigramSimilarity on the primary field for typo tolerance.

    Returns an annotated queryset ordered by combined score.
    """
    search_query = SearchQuery(term, search_type="websearch")

    # 1. FTS rank from the stored GIN-indexed vector
    qs = queryset.annotate(
        fts_rank=SearchRank("search_vector", search_query),
    )

    # 2. Trigram similarity on the first (primary) text field
    primary_field = search_fields_for_trigram[0]
    qs = qs.annotate(
        trigram_sim=TrigramSimilarity(primary_field, term),
    )

    # 3. Combined rank: whichever is higher
    qs = qs.annotate(
        rank=Greatest("fts_rank", "trigram_sim", output_field=FloatField()),
    )

    # 4. Filter: keep rows that matched by either method
    qs = qs.filter(
        Q(fts_rank__gte=FTS_THRESHOLD) | Q(trigram_sim__gte=SIMILARITY_THRESHOLD)
    )

    return qs.order_by("-rank")[:RESULTS_PER_TYPE]


# ---------------------------------------------------------------------------
# API View
# ---------------------------------------------------------------------------
class SearchRateThrottle(UserRateThrottle):
    rate = '30/min'

class GlobalSearchView(APIView):
    throttle_classes = [SearchRateThrottle]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        term = request.query_params.get("q", "").strip()
        if len(term) < 2:
            return Response(
                {"error": "Search query must be at least 2 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        search_type = request.query_params.get("type", "all").lower()
        valid_types = {"all", "users", "workouts", "exercises"}
        if search_type not in valid_types:
            return Response(
                {"error": f"Invalid type. Choose from: {', '.join(valid_types)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = {}

        # --- Users ---
        if search_type in ("all", "users"):
            user_qs = (
                UserProfile.objects
                .filter(Q(is_public=True) | Q(user=request.user))
                .select_related("user")
                .exclude(search_vector=None)
            )
            user_results = _hybrid_search(user_qs, term, ["user__username"])
            results["users"] = UserSearchResultSerializer(user_results, many=True).data

        # --- Exercises ---
        if search_type in ("all", "exercises"):
            exercise_qs = (
                Exercise.objects
                .prefetch_related("muscles")
                .exclude(search_vector=None)
            )
            exercise_results = _hybrid_search(exercise_qs, term, ["name"])
            results["exercises"] = ExerciseSearchResultSerializer(
                exercise_results, many=True
            ).data

        # --- Workouts ---
        if search_type in ("all", "workouts"):
            workout_qs = (
                Workout.objects
                .filter(
                    Q(visibility=Workout.Visibility.PUBLIC)
                    | Q(owner=request.user)
                )
                .select_related("owner__profile")
                .exclude(search_vector=None)
            )
            workout_results = _hybrid_search(workout_qs, term, ["name"])
            results["workouts"] = WorkoutSearchResultSerializer(
                workout_results, many=True
            ).data

        total = sum(len(v) for v in results.values())

        return Response({
            "query": term,
            "results": results,
            "total_count": total,
        })
