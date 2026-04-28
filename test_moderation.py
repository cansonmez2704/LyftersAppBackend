"""End-to-end moderation test.

Run from GymHubBackend/:
    python manage.py shell < test_moderation.py

Three layers, in order:
  1. Direct OpenAI call -> does the API flag the Turkish profanity at all?
  2. Synchronous task run -> does our task code do the right thing on a flag?
  3. Asynchronous dispatch -> does the running Celery worker pick it up?
"""
import time
from django.contrib.contenttypes.models import ContentType
from community.models import Comment
from common.moderation import ModerationResult, ModerationStatus
from common import groq_client
from community.tasks import moderate_content, dispatch_moderation


SAMPLES = [
    "senin annen bir orospu",
    "your mother is a whore",
    "I hope you die you piece of shit",
    "Nice workout!",
]

print("=" * 72)
print("LAYER 1: direct Groq Llama Guard call (bypasses Celery & DB)")
print("=" * 72)
for text in SAMPLES:
    try:
        r = groq_client.moderate_text(text)
        hits = [k for k, v in r.categories.items() if v]
        print(f"  flagged={r.flagged!s:<5}  text={text!r}")
        print(f"     categories hit: {hits or '(none)'}")
    except Exception as e:
        print(f"  ERROR on {text!r}: {type(e).__name__}: {e}")
        print("  -> GROQ_API_KEY missing or invalid? Check env.")
        break

print()
print("=" * 72)
print("LAYER 2: synchronous task (.apply) on the stuck pending comment")
print("=" * 72)
c = Comment.objects.filter(body__icontains="orospu").order_by("-created_at").first()
if not c:
    print("  No 'orospu' comment found in DB.")
else:
    ct_id = ContentType.objects.get_for_model(Comment).id
    print(f"  Before: id={c.pk}  status={c.moderation_status}")
    res = moderate_content.apply(args=[ct_id, c.pk]).result
    print(f"  Task returned: {res!r}")
    c.refresh_from_db()
    print(f"  After : id={c.pk}  status={c.moderation_status}  moderated_at={c.moderated_at}")
    last = ModerationResult.objects.filter(object_id=c.pk).order_by("-created_at").first()
    if last:
        print(f"  Audit row: decision={last.decision} flagged={last.flagged}")
        print(f"             scores={last.category_scores}")
    else:
        print("  No audit row written (task short-circuited).")

print()
print("=" * 72)
print("LAYER 3: async dispatch through Celery worker")
print("=" * 72)
# Reset the comment to pending so we can verify the worker picks it up.
if c:
    Comment.objects.filter(pk=c.pk).update(
        moderation_status=ModerationStatus.PENDING,
        moderated_at=None,
    )
    c.refresh_from_db()
    print(f"  Reset to: status={c.moderation_status}")

    ct_id = ContentType.objects.get_for_model(Comment).id
    dispatch_moderation(ct_id, c.pk)
    print("  Dispatched (3s countdown). Polling status for up to 30s...")

    deadline = time.time() + 30
    while time.time() < deadline:
        c.refresh_from_db()
        if c.moderation_status != ModerationStatus.PENDING:
            break
        time.sleep(1)

    print(f"  Final: status={c.moderation_status}  moderated_at={c.moderated_at}")
    if c.moderation_status == ModerationStatus.PENDING:
        print("  -> Worker did NOT process the task in 30s.")
        print("     Check the celery terminal for errors / queue name mismatch.")
