from django.contrib import admin

from .moderation import ModerationResult


@admin.register(ModerationResult)
class ModerationResultAdmin(admin.ModelAdmin):
    """Read-only audit log of every moderation API call.

    Admins can browse historical decisions, filter by flagged content, and
    inspect raw ``category_scores`` to evaluate threshold tuning.  The model
    is append-only: add/change are disabled; only superusers may delete rows
    (e.g. for GDPR purge requests).
    """

    list_display = (
        "content_type",
        "object_id",
        "decision",
        "flagged",
        "model_name",
        "created_at",
    )
    list_filter = ("decision", "flagged", "content_type", "created_at")
    readonly_fields = (
        "content_type",
        "object_id",
        "decision",
        "flagged",
        "categories",
        "category_scores",
        "model_name",
        "error",
        "created_at",
    )
    search_fields = ("object_id",)
    date_hierarchy = "created_at"
    list_per_page = 50

    fieldsets = (
        ("Target", {
            "fields": ("content_type", "object_id"),
        }),
        ("Decision", {
            "fields": ("decision", "flagged", "model_name"),
        }),
        ("Raw Scores (for threshold tuning)", {
            "fields": ("categories", "category_scores"),
            "classes": ("collapse",),
        }),
        ("Error (if any)", {
            "fields": ("error",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at",),
        }),
    )

    def has_add_permission(self, request):
        return False  # Append-only: rows are created by the Celery task.

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
