from django.db import transaction
from django.db.models import Q, F, Value, Prefetch
from django.db.models.functions import Greatest
from django.shortcuts import get_object_or_404


from rest_framework.viewsets import ModelViewSet
from rest_framework.generics import ListAPIView
from rest_framework.decorators import action
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from django.http import QueryDict

from core.throttles import ReactionSpamThrottle

from common.permissions import IsOwnerOrReadOnly, IsAuthorOnly, IsOwnerOrAdmin, CanCommentOnPost
from common.reactions import toggle_reaction
from common.pagination import FeedCursorPagination, PopularFeedCursorPagination, CommentLimitOffsetPagination


from .serializers import (
    PostListSerializer,
    PostDetailSerializer,
    CommentSerializer,
    PostReactionSerializer,
    PostWriteSerializer,
)
from .models import Post, Comment, PostReaction, CommentReaction, ReactionType
from users.models import UserFollower


def _visible_author_ids(user):
    """Authors the given user has an accepted follow relationship with."""
    return UserFollower.objects.filter(
        from_user=user,
        status=UserFollower.FollowStatus.ACCEPTED,
    ).values("to_user_id")


class PostViewSet(ModelViewSet):
    """Global post CRUD. `list` returns every post the caller may see under
    the visibility rules (public, own, or followers-only from accepted follows).
    For the "people I follow" timeline, use `FeedView` at /feed/ instead."""

    pagination_class = FeedCursorPagination
    lookup_field = 'uuid'
    parser_classes = (JSONParser, FormParser, MultiPartParser)

    def _normalized_write_data(self, request):
        """
        DRF's multipart parsing is inconsistent for nested list serializers.
        Accept common client encodings and normalize into:
            {"media": [{"file": <InMemoryUploadedFile>, "media_type": "...", ...}, ...]}
        """
        data = request.data
        if not isinstance(data, QueryDict):
            return data

        # Avoid QueryDict.copy() / deepcopy: it tries to deepcopy file handles
        # (TemporaryUploadedFile) which can raise pickling errors on large uploads.
        base = data

        # QueryDict -> plain dict (keep last scalar value)
        normalized = {k: base.get(k) for k in base.keys()}

        # Ensure file fields are present on the normalized dict.
        for file_key, file_obj in request.FILES.items():
            normalized[file_key] = file_obj

        media_items = []
        i = 0
        while True:
            # Support both bracket and dotted forms
            file_obj = (
                request.FILES.get(f"media[{i}][file]")
                or request.FILES.get(f"media[{i}].file")
                or request.FILES.get(f"media[{i}]file")
            )
            media_type = (
                base.get(f"media[{i}][media_type]")
                or base.get(f"media[{i}].media_type")
                or base.get(f"media[{i}]media_type")
            )
            order = (
                base.get(f"media[{i}][order]")
                or base.get(f"media[{i}].order")
                or base.get(f"media[{i}]order")
            )
            alt_text = (
                base.get(f"media[{i}][alt_text]")
                or base.get(f"media[{i}].alt_text")
                or base.get(f"media[{i}]alt_text")
                or ""
            )

            if file_obj is None and media_type is None and order is None:
                break

            media_items.append({
                "file": file_obj,
                "media_type": media_type,
                "order": order if order is not None else i,
                "alt_text": alt_text,
            })
            i += 1

        if media_items:
            normalized["media"] = media_items

        return normalized

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=self._normalized_write_data(request))
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance,
            data=self._normalized_write_data(request),
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PostDetailSerializer
        elif self.action in ["create", "update", "partial_update"]:
            return PostWriteSerializer
        return PostListSerializer

    def get_queryset(self):
        base_queryset = Post.objects.filter(is_deleted=False).select_related("author__profile")

        if self.request.user.is_staff:
            queryset = base_queryset
        elif self.request.user.is_authenticated:
            # Subquery-based visibility filter — avoids the M2M join that would
            # otherwise duplicate rows when the author has many followers.
            queryset = base_queryset.filter(
                Q(author=self.request.user)
                | Q(visibility=Post.Visibility.PUBLIC)
                | Q(
                    visibility=Post.Visibility.FOLLOWERS,
                    author_id__in=_visible_author_ids(self.request.user),
                )
            )
        else:
            queryset = base_queryset.filter(visibility=Post.Visibility.PUBLIC)

        if self.action == 'retrieve':
            # Comments and reactions live on their own paginated endpoints —
            # prefetching them here would pull unbounded rows on a single
            # post-retrieve, and reactor profiles add PII exposure.
            return queryset.prefetch_related("media")
        return queryset.prefetch_related("media")

    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwnerOrReadOnly()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def perform_destroy(self, instance):
        # Conditional update: only the first concurrent delete wins, avoiding
        # TOCTOU drift on any future denormalized counters tied to this post.
        Post.objects.filter(pk=instance.pk, is_deleted=False).update(is_deleted=True)

    @action(detail=True, methods=["POST"], url_path="react", throttle_classes=[ReactionSpamThrottle])
    def react_to_posts(self, request, uuid=None):
        post = self.get_object()
        return toggle_reaction(
            reaction_model=PostReaction,
            parent_obj=post,
            parent_field_name="post",
            user=request.user,
            reaction_type=request.data.get("reaction_type"),
            valid_choices=[ReactionType.LIKE, ReactionType.DISLIKE],
        )

    @action(
        detail=True,
        methods=["GET"],
        pagination_class=FeedCursorPagination,
    )
    def reactions(self, request, uuid=None):
        post = self.get_object()
        reaction_qs = (
            post.reactions
            .select_related("user__profile")
            .order_by("-created_at")
        )
        reaction_type = request.query_params.get("type")
        if reaction_type:
            reaction_qs = reaction_qs.filter(reaction_type=reaction_type)

        paginator = self.paginator
        page = paginator.paginate_queryset(reaction_qs, request, view=self)
        serializer = PostReactionSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class CommentViewSet(ModelViewSet):
    serializer_class = CommentSerializer
    pagination_class = CommentLimitOffsetPagination
    lookup_field = "uuid"
    lookup_url_kwarg = "comment_uuid"

    def get_permissions(self):
        if self.action in ['update', 'partial_update']:
            return [permissions.IsAuthenticated(), IsAuthorOnly()]
        if self.action == 'destroy':
            return [permissions.IsAuthenticated(), IsOwnerOrAdmin()]
        if self.action == 'create':
            return [permissions.IsAuthenticated(), CanCommentOnPost()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        queryset = Comment.objects.filter(is_deleted=False)
        if self.request.user.is_staff or self.request.user.is_superuser:
            base = queryset
        else:
            # Subquery avoids row duplication from the M2M follower join.
            base = queryset.filter(
                Q(post__visibility=Post.Visibility.PUBLIC)
                | Q(post__author=self.request.user)
                | Q(
                    post__visibility=Post.Visibility.FOLLOWERS,
                    post__author_id__in=_visible_author_ids(self.request.user),
                )
            )

        post_uuid = self.kwargs.get('post_uuid') or self.request.query_params.get('post')
        if post_uuid:
            base = base.filter(post__uuid=post_uuid)

        parent_uuid = self.kwargs.get("parent_uuid")
        if parent_uuid:
            base = base.filter(parent__uuid=parent_uuid)
        elif self.action == "list" and post_uuid:
            # Top-level comments only on the post-comments list; replies are
            # fetched via /comments/<uuid>/replies/.
            base = base.filter(parent__isnull=True)

        return base.select_related("post", "author__profile").prefetch_related("reactions__user__profile")

    def perform_create(self, serializer):
        post = get_object_or_404(
            Post.objects.filter(is_deleted=False),
            uuid=self.kwargs["post_uuid"],
        )
        self.check_object_permissions(self.request, post)
        serializer.save(author=self.request.user, post=post)
        Post.objects.filter(pk=post.pk).update(comments_count=F("comments_count") + 1)

    def perform_destroy(self, instance):
        # Atomic conditional soft-delete: only the first delete wins, so the
        # comments_count decrement never runs twice for the same comment.
        # Children keep their parent link + depth; the UI greys out the
        # deleted node via `is_deleted`, preserving the reply tree structure.
        updated = Comment.objects.filter(pk=instance.pk, is_deleted=False).update(is_deleted=True)
        if not updated:
            return

        Post.objects.filter(pk=instance.post_id).update(
            comments_count=Greatest(F("comments_count") - 1, Value(0))
        )

    @action(detail=True, methods=["POST"], url_path="react", throttle_classes=[ReactionSpamThrottle])
    def react_to_comments(self, request, comment_uuid=None):
        comment = self.get_object()
        return toggle_reaction(
            reaction_model=CommentReaction,
            parent_obj=comment,
            parent_field_name="comment",
            user=request.user,
            reaction_type=request.data.get("reaction_type"),
            valid_choices=[ReactionType.LIKE, ReactionType.DISLIKE],
        )


class FeedView(ListAPIView):
    """Blended feed: posts from followed users, own posts, and all public
    posts.  Supports two ordering modes via ``?ordering=`` query param:

    * ``recent`` (default) — reverse-chronological, cursor on ``created_at``.
    * ``popular`` — engagement-ranked (``likes_count`` DESC, ``created_at``
      DESC as tiebreaker), cursor on ``(likes_count, created_at)``.

    Both modes are backed by composite B-tree indexes so Postgres can satisfy
    the full ORDER BY + WHERE from a single index scan even at millions of
    rows.

    The combined ``Q(followed) | Q(own) | Q(public)`` filter produces a
    single WHERE clause with OR predicates — no JOINs that could multiply
    rows — so ``DISTINCT`` is unnecessary.
    """

    serializer_class = PostListSerializer
    permission_classes = [permissions.IsAuthenticated]

    # Dynamic: overridden in ``get_pagination_class`` based on query param.
    pagination_class = FeedCursorPagination

    _VALID_ORDERINGS = frozenset({"recent", "popular"})

    @property
    def paginator(self):
        """Switch pagination class (and therefore cursor ordering) based on
        the ``?ordering`` query param.  DRF caches ``self._paginator`` after
        the first call, so the branch is evaluated once per request."""
        if not hasattr(self, "_paginator"):
            mode = self.request.query_params.get("ordering", "recent")
            if mode == "popular":
                self._paginator = PopularFeedCursorPagination()
            else:
                self._paginator = FeedCursorPagination()
        return self._paginator

    def get_queryset(self):
        user = self.request.user

        if user.is_staff:
            qs = (
                Post.objects
                .filter(is_deleted=False)
                .select_related("author", "author__profile")
                .prefetch_related("media")
            )
        else:
            following_ids = (
                UserFollower.objects
                .filter(
                    from_user=user,
                    status=UserFollower.FollowStatus.ACCEPTED,
                )
                .values("to_user_id")
            )

            qs = (
                Post.objects
                .filter(
                    Q(author_id__in=following_ids)
                    | Q(author=user)
                    | Q(visibility=Post.Visibility.PUBLIC),
                    is_deleted=False,
                )
                .select_related("author__profile")
                .prefetch_related("media")
            )

        mode = self.request.query_params.get("ordering", "recent")
        if mode == "popular":
            return qs.order_by("-likes_count", "-created_at")
        return qs.order_by("-created_at")
