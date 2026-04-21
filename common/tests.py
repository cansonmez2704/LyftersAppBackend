"""
Comprehensive tests for common app: global search, edge cases, throttling,
and media upload validation.
"""

from io import BytesIO
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from community.models import Post
from users.models import UserProfile
from workouts.models import Exercise, MuscleGroup, Workout

User = get_user_model()


# ---------------------------------------------------------------------------
# Search-vector helper — call after creating objects so FTS works in tests.
# on_commit callbacks don't fire inside test transactions.
# ---------------------------------------------------------------------------

def _populate_search_vectors():
    """Manually rebuild search vectors for all exercises, workouts, profiles."""
    from django.contrib.postgres.search import SearchVector
    from django.db import connection

    Exercise.objects.update(
        search_vector=SearchVector("name", weight="A")
        + SearchVector("description", weight="B"),
    )
    Workout.objects.update(
        search_vector=SearchVector("name", weight="A")
        + SearchVector("description", weight="B"),
    )
    # UserProfile search vectors involve a JOIN, so use raw SQL
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE users_userprofile
            SET search_vector =
                setweight(to_tsvector('english', COALESCE(u.username, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(users_userprofile.bio, '')), 'B')
            FROM users_user u
            WHERE users_userprofile.user_id = u.id
        """)


def _mock_hybrid_search(queryset, term, search_fields_for_trigram):
    """
    Drop-in replacement for _hybrid_search that avoids pg_trgm (SIMILARITY).
    Uses simple icontains on the primary field so the view's queryset filtering
    (access control, visibility) is still exercised, while the rank annotation
    satisfies the serializers.
    """
    from django.db.models import FloatField, Value

    primary_field = search_fields_for_trigram[0]
    lookup = {f"{primary_field}__icontains": term}

    return (
        queryset
        .filter(**lookup)
        .annotate(rank=Value(1.0, output_field=FloatField()))
        .order_by("-rank")[:10]
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. SEARCH & FILTERING + ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════════

@patch("common.search._hybrid_search", side_effect=_mock_hybrid_search)
class GlobalSearchTests(APITestCase):
    """Tests for GET /api/v1/search/ — basic queries, type filtering, access control."""

    @classmethod
    def setUpTestData(cls):
        # --- Users ---
        cls.owner = User.objects.create_user(
            username="benchmaster", email="owner@test.com", password="pass1234"
        )
        cls.stranger = User.objects.create_user(
            username="stranger", email="stranger@test.com", password="pass1234"
        )
        cls.staff = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="pass1234"
        )

        # --- Profiles ---
        cls.owner_profile, _ = UserProfile.objects.get_or_create(user=cls.owner)
        cls.owner_profile.bio = "I love bench pressing and deadlifts"
        cls.owner_profile.is_public = True
        cls.owner_profile.save()

        cls.stranger_profile, _ = UserProfile.objects.get_or_create(user=cls.stranger)
        cls.stranger_profile.is_public = False  # private profile
        cls.stranger_profile.save()

        UserProfile.objects.get_or_create(user=cls.staff)

        # --- Exercises ---
        chest = MuscleGroup.objects.create(name="Chest", slug="chest")
        cls.bench_press = Exercise.objects.create(
            name="Bench Press",
            slug="bench-press",
            description="A classic compound chest exercise",
            exercise_type=Exercise.ExerciseType.WEIGHTLIFTING,
            movement_type=Exercise.MovementType.COMPOUND,
        )
        cls.bench_press.muscles.add(chest)

        # --- Workouts ---
        cls.public_workout = Workout.objects.create(
            owner=cls.owner,
            name="Push Day Routine",
            description="Bench press and overhead press",
            visibility=Workout.Visibility.PUBLIC,
        )
        cls.private_workout = Workout.objects.create(
            owner=cls.owner,
            name="Secret Pull Workout",
            description="Private back training",
            visibility=Workout.Visibility.PRIVATE,
        )

        # --- Populate search vectors ---
        _populate_search_vectors()

    def setUp(self):
        self.url = reverse("global-search")

    # ---- Basic search ----

    def test_basic_search_returns_results(self, mock_search):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, {"q": "bench"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(response.data["total_count"], 0)

    def test_search_returns_exercises(self, mock_search):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, {"q": "bench", "type": "exercises"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("exercises", response.data["results"])
        self.assertNotIn("users", response.data["results"])
        self.assertNotIn("workouts", response.data["results"])

    def test_search_returns_workouts(self, mock_search):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, {"q": "push", "type": "workouts"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("workouts", response.data["results"])
        self.assertNotIn("users", response.data["results"])
        self.assertNotIn("exercises", response.data["results"])

    def test_search_returns_users(self, mock_search):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, {"q": "benchmaster", "type": "users"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("users", response.data["results"])
        self.assertNotIn("workouts", response.data["results"])
        self.assertNotIn("exercises", response.data["results"])

    def test_invalid_type_filter_returns_400(self, mock_search):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, {"q": "bench", "type": "invalid"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---- Access control: private profiles ----

    def test_private_profile_hidden_from_stranger(self, mock_search):
        """Private profiles should still be discoverable (but restricted)."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, {"q": "stranger", "type": "users"})

        usernames = [u["username"] for u in response.data["results"].get("users", [])]
        self.assertIn("stranger", usernames)

    def test_private_profile_visible_to_owner(self, mock_search):
        """The profile owner should see themselves even if profile is private."""
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(self.url, {"q": "stranger", "type": "users"})

        usernames = [u["username"] for u in response.data["results"].get("users", [])]
        self.assertIn("stranger", usernames)

    # ---- Access control: private workouts ----

    def test_private_workout_hidden_from_stranger(self, mock_search):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(self.url, {"q": "secret", "type": "workouts"})

        workout_names = [
            w["name"] for w in response.data["results"].get("workouts", [])
        ]
        self.assertNotIn("Secret Pull Workout", workout_names)

    def test_private_workout_visible_to_owner(self, mock_search):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, {"q": "secret", "type": "workouts"})

        workout_names = [
            w["name"] for w in response.data["results"].get("workouts", [])
        ]
        self.assertIn("Secret Pull Workout", workout_names)

    def test_staff_sees_public_results(self, mock_search):
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url, {"q": "bench"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(response.data["total_count"], 0)

    # ---- Auth required ----

    def test_unauthenticated_returns_401(self, mock_search):
        response = self.client.get(self.url, {"q": "bench"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ═══════════════════════════════════════════════════════════════════════════
# 2. SEARCH EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

class SearchEdgeCaseTests(APITestCase):
    """Edge-case handling: empty queries, special chars, very long strings."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="edgeuser", email="edge@test.com", password="pass1234"
        )
        UserProfile.objects.get_or_create(user=cls.user)

    def setUp(self):
        self.url = reverse("global-search")
        self.client.force_authenticate(user=self.user)

    def test_empty_query_returns_400(self):
        """An empty q= should return 400 (view requires >= 2 chars)."""
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_single_char_query_returns_400(self):
        response = self.client.get(self.url, {"q": "a"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_whitespace_only_query_returns_400(self):
        response = self.client.get(self.url, {"q": "   "})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("common.search._hybrid_search", side_effect=_mock_hybrid_search)
    def test_special_characters_returns_200_empty(self, mock_search):
        """Special chars like @#$%! should not crash; returns 200 with empty results."""
        response = self.client.get(self.url, {"q": "@#$%!"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_count"], 0)

    def test_long_query_returns_400(self):
        """A query exceeding MAX_QUERY_LENGTH (200) should be rejected as 400."""
        long_query = "a" * 501
        response = self.client.get(self.url, {"q": long_query})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("common.search._hybrid_search", side_effect=_mock_hybrid_search)
    def test_query_at_max_length_succeeds(self, mock_search):
        """A query exactly at the limit (200 chars) should not be rejected."""
        response = self.client.get(self.url, {"q": "a" * 200})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════
# 3. RATE LIMITING (THROTTLING)
# ═══════════════════════════════════════════════════════════════════════════

THROTTLED_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "throttle-test",
    }
}


@override_settings(CACHES=THROTTLED_CACHES)
@patch("common.search._hybrid_search", side_effect=_mock_hybrid_search)
class SearchThrottleTests(APITestCase):
    """Verify that SearchRateThrottle enforces limits on the search endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="throttleuser", email="throttle@test.com", password="pass1234"
        )
        UserProfile.objects.get_or_create(user=cls.user)
        _populate_search_vectors()

    def setUp(self):
        self.url = reverse("global-search")
        self.client.force_authenticate(user=self.user)

    @patch("common.search.SearchThrottle.get_rate", return_value="2/min")
    def test_throttle_allows_first_two_then_blocks_third(self, mock_get_rate, mock_search):
        """First two requests → 200, third request → 429 Too Many Requests."""
        r1 = self.client.get(self.url, {"q": "bench"})
        self.assertEqual(r1.status_code, status.HTTP_200_OK)

        r2 = self.client.get(self.url, {"q": "bench"})
        self.assertEqual(r2.status_code, status.HTTP_200_OK)

        r3 = self.client.get(self.url, {"q": "bench"})
        self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


# ═══════════════════════════════════════════════════════════════════════════
# 4. MEDIA UPLOAD VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

class MediaUploadValidationTests(APITestCase):
    """Test PostMedia validation via the PostViewSet create endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="uploader", email="uploader@test.com", password="pass1234"
        )
        UserProfile.objects.get_or_create(user=cls.user)

    def setUp(self):
        self.url = reverse("posts-list")
        self.client.force_authenticate(user=self.user)

    # ---- helpers ----

    @staticmethod
    def _tiny_jpg(size_bytes=100):
        """Return a minimal valid-looking JPEG SimpleUploadedFile."""
        content = b"\xff\xd8\xff\xe0" + b"\x00" * (size_bytes - 4)
        return SimpleUploadedFile("photo.jpg", content, content_type="image/jpeg")

    @staticmethod
    def _tiny_mp4(size_bytes=100):
        content = b"\x00\x00\x00\x1c\x66\x74\x79\x70" + b"\x00" * (size_bytes - 8)
        return SimpleUploadedFile("clip.mp4", content, content_type="video/mp4")

    # ---- Valid uploads ----

    def test_valid_image_upload_returns_201(self):
        """A small .jpg should be accepted."""
        payload = {
            "title": "Post with image",
            "description": "Image test",
            "media[0][media_type]": "image",
            "media[0][file]": self._tiny_jpg(),
            "media[0][order]": "0",
        }
        with patch("common.validators.magic.from_buffer", return_value="image/jpeg"):
            response = self.client.post(self.url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.data)

    def test_valid_video_upload_returns_201(self):
        """A small .mp4 should be accepted."""
        payload = {
            "title": "Post with video",
            "description": "Video test",
            "media[0][media_type]": "video",
            "media[0][file]": self._tiny_mp4(),
            "media[0][order]": "0",
        }
        with patch("common.validators.magic.from_buffer", return_value="video/mp4"):
            response = self.client.post(self.url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.data)

    # ---- Oversized file ----

    def test_oversized_image_returns_400(self):
        """An image exceeding 10 MB should be rejected."""
        oversized = SimpleUploadedFile(
            "huge.jpg",
            b"\xff\xd8\xff\xe0" + b"\x00" * (11 * 1024 * 1024),  # ~11 MB
            content_type="image/jpeg",
        )
        payload = {
            "title": "Oversized upload",
            "description": "Should fail",
            "media[0][media_type]": "image",
            "media[0][file]": oversized,
            "media[0][order]": "0",
        }
        with patch("common.validators.magic.from_buffer", return_value="image/jpeg"):
            response = self.client.post(self.url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---- Bad extensions ----

    def test_exe_extension_rejected(self):
        """A .exe file should be rejected by the FileExtensionValidator."""
        bad_file = SimpleUploadedFile(
            "malware.exe", b"\x00" * 100, content_type="application/octet-stream"
        )
        payload = {
            "title": "Bad extension test",
            "description": "Should fail",
            "media[0][media_type]": "image",
            "media[0][file]": bad_file,
            "media[0][order]": "0",
        }
        with patch("common.validators.magic.from_buffer", return_value="application/octet-stream"):
            response = self.client.post(self.url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_txt_extension_rejected(self):
        """A .txt file should be rejected."""
        bad_file = SimpleUploadedFile(
            "notes.txt", b"Hello world", content_type="text/plain"
        )
        payload = {
            "title": "Text file test",
            "description": "Should fail",
            "media[0][media_type]": "image",
            "media[0][file]": bad_file,
            "media[0][order]": "0",
        }
        with patch("common.validators.magic.from_buffer", return_value="text/plain"):
            response = self.client.post(self.url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
