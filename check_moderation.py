"""One-shot diagnostic: why didn't the bad-word comment get rejected?

Run from the GymHubBackend dir:
    python manage.py shell < check_moderation.py
"""
from community.models import Comment
from common.moderation import ModerationResult

qs = Comment.objects.filter(body__icontains="orospu").order_by("-created_at")
print(f"Found {qs.count()} comment(s) containing 'orospu'")

for c in qs[:5]:
    print("-" * 70)
    print(f"id={c.pk}  uuid={c.uuid}")
    print(f"body            : {c.body!r}")
    print(f"moderation_status: {c.moderation_status}")
    print(f"requires_manual : {c.requires_manual_review}")
    print(f"moderated_at    : {c.moderated_at}")
    print(f"created_at      : {c.created_at}")

    results = list(
        ModerationResult.objects.filter(object_id=c.pk).values(
            "decision", "flagged", "categories", "category_scores", "error", "model_name"
        )
    )
    if not results:
        print("ModerationResult: NONE  -> Celery task never ran (or task crashed before logging)")
    else:
        for r in results:
            print(f"ModerationResult: {r}")
