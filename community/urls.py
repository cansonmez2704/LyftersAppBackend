from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PostViewSet, CommentViewSet, FeedView

router = DefaultRouter()
router.register(r"posts", PostViewSet, basename="posts")

urlpatterns = [
    path("", include(router.urls)),
    path("feed/", FeedView.as_view(), name="feed"),

    # Top-level comments under a specific post
    path(
        "posts/<uuid:post_uuid>/comments/",
        CommentViewSet.as_view({"get": "list", "post": "create"}),
        name="post-comments",
    ),

    # Flat detail for a single comment
    path(
        "comments/<uuid:comment_uuid>/",
        CommentViewSet.as_view({
            "get": "retrieve",
            "patch": "partial_update",
            "delete": "destroy",
        }),
        name="comment-detail",
    ),

    # React to a comment
    path(
        "comments/<uuid:comment_uuid>/react/",
        CommentViewSet.as_view({"post": "react_to_comments"}),
        name="comment-react",
    ),

    # Replies to a comment — paginated list, scoped by parent UUID
    path(
        "comments/<uuid:parent_uuid>/replies/",
        CommentViewSet.as_view({"get": "list"}),
        name="comment-replies",
    ),
]
