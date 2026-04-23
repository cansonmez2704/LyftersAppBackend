from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from rest_framework.throttling import ScopedRateThrottle
from .views import (
    RegisterView, MyProfileView, UserProfileView,
    LogoutView, ChangePasswordView,
    FollowUserView, AcceptFollowView, RejectFollowView,
    FollowerListView, FollowingListView,
    SuggestionsView,
    IncomingFollowRequestsView,
    GoogleLoginView, GoogleClientIdView,
)


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'


class ThrottledTokenVerifyView(TokenVerifyView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'


urlpatterns = [
    # Auth
    path("token/refresh/", ThrottledTokenRefreshView.as_view(), name='token_refresh'),
    path("token/verify/", ThrottledTokenVerifyView.as_view(), name='token_verify'),
    path("sign-up/", RegisterView.as_view(), name="sign-up"),
    path("log-out/", LogoutView.as_view(), name="logout"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),

    # Google OAuth2
    path("auth/google/", GoogleLoginView.as_view(), name="google-login"),
    path("auth/google/client-id/", GoogleClientIdView.as_view(), name="google-client-id"),

    # Profile
    path("my-profile/", MyProfileView.as_view(), name="my-profile"),
    path("profiles/<uuid:uuid>/", UserProfileView.as_view(), name="user-profile"),

    # Follow actions
    path("profiles/<uuid:uuid>/follow/", FollowUserView.as_view(), name="follow-user"),
    path("follow-requests/<uuid:uuid>/accept/", AcceptFollowView.as_view(), name="accept-follow"),
    path("follow-requests/<uuid:uuid>/reject/", RejectFollowView.as_view(), name="reject-follow"),

    # Follower / Following lists
    path("profiles/<uuid:uuid>/followers/", FollowerListView.as_view(), name="follower-list"),
    path("profiles/<uuid:uuid>/following/", FollowingListView.as_view(), name="following-list"),

    # Suggestions
    path("suggestions/", SuggestionsView.as_view(), name="profile-suggestions"),

    # Incoming follow requests (for private accounts)
    path("follow-requests/", IncomingFollowRequestsView.as_view(), name="incoming-follow-requests"),
]