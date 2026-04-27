from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import Post, PostMedia, Comment, PostReaction, CommentReaction



class PostMediaInline(admin.TabularInline):
    model = PostMedia
    extra = 1
    fields = ("order", "media_type", "file", "alt_text")
    ordering = ("order",)


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ("author", "body", "is_deleted", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True




@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = (
        "title_display",
        "author",
        "post_type",
        "visibility",
        "moderation_status",
        "requires_manual_review",
        "likes_count",
        "dislikes_count",
        "comments_count",
        "is_pinned",
        "is_archived",
        "is_deleted",
        "created_at",
    )
    list_filter  = ("moderation_status", "requires_manual_review", "post_type", "visibility", "is_pinned", "is_archived", "created_at")
    search_fields = ("title", "description", "author__username", "slug")
    readonly_fields = (
        "uuid",
        "slug",
        "likes_count",
        "dislikes_count",
        "comments_count",
        "moderated_at",
        "created_at",
        "updated_at",
    )
    list_editable = ("is_pinned", "is_archived","is_deleted")
    inlines = [PostMediaInline, CommentInline]
    fieldsets = (
        ("Content", {
            "fields": ("author", "title", "slug", "description", "cover_image"),
        }),
        ("Classification", {
            "fields": ("post_type", "visibility", "linked_workout"),
        }),
        ("Moderation", {
            "fields": ("moderation_status", "requires_manual_review", "moderated_at"),
        }),
        ("Flags", {
            "fields": ("is_pinned", "is_archived"),
        }),
        ("Engagement (read-only)", {
            "fields": ("likes_count", "dislikes_count", "comments_count"),
            "classes": ("collapse",),
        }),
        ("Meta", {
            "fields": ("uuid", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Title")
    def title_display(self, obj):
        return obj.title or f"Post #{str(obj.uuid)[:8]}"

    # Bulk actions
    @admin.action(description="Pin selected posts")
    def pin_posts(self, request, queryset):
        queryset.update(is_pinned=True)

    @admin.action(description="Unpin selected posts")
    def unpin_posts(self, request, queryset):
        queryset.update(is_pinned=False)

    @admin.action(description="Archive selected posts")
    def archive_posts(self, request, queryset):
        queryset.update(is_archived=True)

    @admin.action(description="Unarchive selected posts")
    def unarchive_posts(self, request, queryset):
        queryset.update(is_archived=False)

    @admin.action(description="✅ Approve selected posts (set PUBLISHED)")
    def approve_posts(self, request, queryset):
        queryset.update(
            moderation_status="published",
            requires_manual_review=False,
            moderated_at=timezone.now(),
        )

    @admin.action(description="❌ Reject selected posts")
    def reject_posts(self, request, queryset):
        queryset.update(
            moderation_status="rejected",
            requires_manual_review=False,
            moderated_at=timezone.now(),
        )

    actions = [
        "pin_posts", "unpin_posts", "archive_posts", "unarchive_posts",
        "approve_posts", "reject_posts",
    ]



@admin.register(PostMedia)
class PostMediaAdmin(admin.ModelAdmin):
    list_display  = ("__str__", "post", "media_type", "order")
    list_filter   = ("media_type",)
    search_fields = ("post__title", "alt_text")



@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display  = ("short_body", "author", "post", "parent", "moderation_status", "requires_manual_review", "likes_count", "dislikes_count", "is_deleted", "created_at")
    list_filter   = ("moderation_status", "requires_manual_review", "is_deleted", "created_at")
    search_fields = ("body", "author__username", "post__title")
    readonly_fields = ("created_at", "updated_at", "moderated_at")
    list_editable = ("is_deleted",)
    fieldsets = (
        ("Comment", {
            "fields": ("post", "author", "parent", "body"),
        }),
        ("Moderation", {
            "fields": ("moderation_status", "requires_manual_review", "moderated_at", "is_deleted"),
        }),
        ("Engagement (read-only)", {
            "fields": ("likes_count", "dislikes_count"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Body")
    def short_body(self, obj):
        return obj.body[:80] + ("…" if len(obj.body) > 80 else "")

    @admin.action(description="Soft-delete selected comments")
    def soft_delete_comments(self, request, queryset):
        queryset.update(is_deleted=True)

    @admin.action(description="Restore selected comments")
    def restore_comments(self, request, queryset):
        queryset.update(is_deleted=False)

    @admin.action(description="✅ Approve selected comments (set PUBLISHED)")
    def approve_comments(self, request, queryset):
        queryset.update(
            moderation_status="published",
            requires_manual_review=False,
            moderated_at=timezone.now(),
        )

    @admin.action(description="❌ Reject selected comments")
    def reject_comments(self, request, queryset):
        queryset.update(
            moderation_status="rejected",
            requires_manual_review=False,
            moderated_at=timezone.now(),
        )

    actions = ["soft_delete_comments", "restore_comments", "approve_comments", "reject_comments"]



@admin.register(PostReaction)
class PostReactionAdmin(admin.ModelAdmin):
    list_display  = ("user", "post", "reaction_type", "created_at")
    list_filter   = ("reaction_type", "created_at")
    search_fields = ("user__username", "post__title")
    readonly_fields = ("created_at",)




@admin.register(CommentReaction)
class CommentReactionAdmin(admin.ModelAdmin):
    list_display  = ("user", "comment", "reaction_type", "created_at")
    list_filter   = ("reaction_type", "created_at")
    search_fields = ("user__username",)
    readonly_fields = ("created_at",)
