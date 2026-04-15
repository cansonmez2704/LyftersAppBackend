from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

class IsOwnerOrReadOnly(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        elif hasattr(obj,"owner"):
            return obj.owner == request.user or request.user.is_staff
        elif hasattr(obj,"author"):
            return obj.author == request.user or request.user.is_staff
        elif hasattr(obj,"user"):
            return obj.user == request.user or request.user.is_staff
        else:
            return False


class IsAuthorOnly(permissions.BasePermission):
    """Only the object's author can write — staff is NOT granted write access."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        elif hasattr(obj, "author"):
            return obj.author == request.user
        elif hasattr(obj, "owner"):
            return obj.owner == request.user
        elif hasattr(obj, "user"):
            return obj.user == request.user
        return False


class IsOwnerOrAdmin(permissions.BasePermission):
    """Object owner or staff/admin can write."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user and request.user.is_staff:
            return True
        elif hasattr(obj, "author"):
            return obj.author == request.user
        elif hasattr(obj, "owner"):
            return obj.owner == request.user
        elif hasattr(obj, "user"):
            return obj.user == request.user
        return False


class CanCommentOnPost(permissions.BasePermission):
    """
    Checks whether the requesting user is allowed to comment on a given post.
    The post is passed as the object to has_object_permission().
    """

    def has_object_permission(self, request, view, post):
        from users.models import UserFollower
        from community.models import Post

        if post.is_deleted:
            raise PermissionDenied("Cannot comment on a deleted post.")

        if post.visibility == Post.Visibility.PRIVATE and post.author != request.user:
            raise PermissionDenied("You cannot comment on this private post.")

        if post.visibility == Post.Visibility.FOLLOWERS and post.author != request.user:
            is_follower = UserFollower.objects.filter(
                from_user=request.user,
                to_user=post.author,
                status=UserFollower.FollowStatus.ACCEPTED,
            ).exists()
            if not is_follower:
                raise PermissionDenied("You must follow this user to comment on their posts.")

        return True
