import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, F
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework import generics, status
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from common.follow import toggle_follow
from common.pagination import FeedCursorPagination
from common.utils import lock_profiles_for_update
from .models import UserProfile, UserFollower
from .serializers import (
    ChangePasswordSerializer,
    FollowerListEntrySerializer,
    FollowingListEntrySerializer,
    FullUserProfileSerializer,
    IncomingFollowRequestSerializer,
    MiniUserProfileSerializer,
    OwnProfileSerializer,
    UserRegisterSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def _client_ip(request) -> str:
    """Best-effort client IP for audit logs. Trusts X-Forwarded-For's leftmost
    entry; upstream proxy/WAF must already be configured to strip spoofed
    values before the request reaches Django."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "-")


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny,]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)

        logger.info(
            "auth.register user_id=%s username=%s ip=%s",
            user.id, user.username, _client_ip(request),
        )

        return Response({
            "message": "Account created successfully!",
            "user": serializer.data,
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required to log out."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            token = RefreshToken(refresh_token)

            # Ensure the token belongs to the authenticated user. Without this a
            # caller who has somehow obtained another user's refresh token could
            # force-log-out that user. We return the same generic error as a
            # malformed-token case so we do not confirm whether the token is
            # simply invalid or belongs to a different account.
            token_user_id = token.get("user_id")
            if token_user_id is None or int(token_user_id) != request.user.id:
                return Response(
                    {"error": "Token is invalid or already logged out."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            token.blacklist()
            logger.info(
                "auth.logout user_id=%s ip=%s",
                request.user.id, _client_ip(request),
            )
            return Response(status=status.HTTP_204_NO_CONTENT)

        except TokenError:
            return Response(
                {"error": "Token is invalid or already logged out."},
                status=status.HTTP_400_BAD_REQUEST
            )

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'

    def put(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        from users.tasks import blacklist_user_tokens

        # Password change + token revocation must be atomic. If the blacklist
        # step fails mid-flight we need the password change to roll back too,
        # otherwise the user believes they have cut off existing sessions
        # while old refresh tokens continue to work.
        user = request.user
        with transaction.atomic():
            user.set_password(serializer.validated_data['new_password'])
            user.save(update_fields=["password"])
            blacklist_user_tokens(user.id)

        logger.info(
            "auth.password_change user_id=%s ip=%s",
            user.id, _client_ip(request),
        )

        return Response(
            {"message": "Password updated successfully."},
            status=status.HTTP_200_OK
        )

class MyProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = OwnProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user.profile
    
class UserProfileView(generics.RetrieveAPIView):
    lookup_field = "user__uuid"
    lookup_url_kwarg = "uuid"
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserProfile.objects.select_related("user")

    def retrieve(self, request, *args, **kwargs):
        profile = self.get_object()

        is_owner = (profile.user == request.user)
        is_admin = request.user.is_staff
        is_public = profile.is_public

        if is_owner or is_admin or is_public:
            serializer = FullUserProfileSerializer(profile, context={'request': request})
        else:
            serializer = MiniUserProfileSerializer(profile, context={'request': request})
        return Response(serializer.data)


class FollowUserView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'social_write'

    def post(self, request, uuid):
        target_profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            user__uuid=uuid,
        )
        return toggle_follow(
            follow_model=UserFollower,
            from_user=request.user,
            target_profile=target_profile,
        )


class AcceptFollowView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'social_write'

    def post(self, request, uuid):
        follow_request = get_object_or_404(
            UserFollower,
            from_user__uuid=uuid,
            to_user=request.user,
            status=UserFollower.FollowStatus.PENDING,
        )

        with transaction.atomic():
            follower_profile_pk = UserProfile.objects.filter(user=follow_request.from_user).values_list("pk", flat=True).first()
            target_profile_pk = request.user.profile.pk

            # Use the DRY locking utility we created to prevent deadlocks
            locked_profiles = lock_profiles_for_update(target_profile_pk, follower_profile_pk, UserProfile)

            follow_request.status = UserFollower.FollowStatus.ACCEPTED
            follow_request.save(update_fields=["status"])

            UserProfile.objects.filter(pk=target_profile_pk).update(
                followers_count=F("followers_count") + 1,
            )
            UserProfile.objects.filter(pk=follower_profile_pk).update(
                following_count=F("following_count") + 1,
            )

        return Response({"status": "Follow request accepted"}, status=status.HTTP_200_OK)


class SuggestionsView(generics.ListAPIView):
    """
    Lightweight "people you may want to follow" endpoint.
    Optimized to use database-level anti-joins instead of pulling large datasets into memory.
    """
    serializer_class = MiniUserProfileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        limit = int(self.request.query_params.get("limit", 8))
        limit = max(1, min(limit, 50))

        # OPTIMIZATION: Database-level ~Q exclusion ensures memory usage stays flat at scale.
        # Private profiles must never be suggested — they explicitly opted out of discovery.
        return (
            UserProfile.objects
            .filter(is_public=True)
            .exclude(user=self.request.user)
            .filter(~Q(user__incoming_followers__from_user=self.request.user))
            .select_related("user")
            .order_by("-followers_count", "-updated_at")[:limit]
        )

class RejectFollowView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'social_write'

    def post(self, request, uuid):
        follow_request = get_object_or_404(
            UserFollower,
            from_user__uuid=uuid,
            to_user=request.user,
            status=UserFollower.FollowStatus.PENDING,
        )
        follow_request.delete()
        return Response({"status": "Follow request rejected"}, status=status.HTTP_200_OK)

def _assert_can_view_follow_list(target_profile, request_user):
    """Private profiles are only enumerable by the owner or an accepted follower.
    Raises PermissionDenied otherwise."""
    if target_profile.is_public or target_profile.user == request_user:
        return
    has_access = UserFollower.objects.filter(
        from_user=request_user,
        to_user=target_profile.user,
        status=UserFollower.FollowStatus.ACCEPTED,
    ).exists()
    if not has_access:
        raise PermissionDenied("This profile is private.")


class FollowerListView(generics.ListAPIView):
    """People who follow the target user, ordered by most recent follow first."""

    serializer_class = FollowerListEntrySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedCursorPagination
    filter_backends = [SearchFilter]
    search_fields = ["from_user__username"]

    def get_queryset(self):
        target_profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            user__uuid=self.kwargs["uuid"],
        )
        _assert_can_view_follow_list(target_profile, self.request.user)

        # Paginating the UserFollower edge directly lets the cursor order by
        # follow recency instead of by the followed profile's creation date.
        return (
            UserFollower.objects
            .filter(
                to_user=target_profile.user,
                status=UserFollower.FollowStatus.ACCEPTED,
            )
            .select_related("from_user__profile", "from_user")
        )


class FollowingListView(generics.ListAPIView):
    """People the target user follows, ordered by most recent follow first."""

    serializer_class = FollowingListEntrySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedCursorPagination
    filter_backends = [SearchFilter]
    search_fields = ["to_user__username"]

    def get_queryset(self):
        target_profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            user__uuid=self.kwargs["uuid"],
        )
        _assert_can_view_follow_list(target_profile, self.request.user)

        return (
            UserFollower.objects
            .filter(
                from_user=target_profile.user,
                status=UserFollower.FollowStatus.ACCEPTED,
            )
            .select_related("to_user__profile", "to_user")
        )


class IncomingFollowRequestsView(generics.ListAPIView):
    """Pending follow requests to the current user (for private accounts)."""

    serializer_class = IncomingFollowRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedCursorPagination

    def get_queryset(self):
        return (
            UserFollower.objects
            .filter(
                to_user=self.request.user,
                status=UserFollower.FollowStatus.PENDING,
            )
            .select_related("from_user__profile", "from_user")
        )

