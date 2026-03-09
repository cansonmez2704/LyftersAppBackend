from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import (
    RegisterView, MyProfileView, UserProfileView,
    LogoutView, ChangePasswordView,
    FollowUserView, AcceptFollowView, RejectFollowView,
    FollowerListView, FollowingListView,
)

urlpatterns = [
    # Auth
    path("token/refresh/", TokenRefreshView.as_view(), name='token_refresh'),
    path("token/verify/", TokenVerifyView.as_view(), name='token_verify'),
    path("sign-up/", RegisterView.as_view(), name="sign-up"),
    path("log-out/", LogoutView.as_view(), name="log-out"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),

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
]