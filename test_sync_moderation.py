"""Drive the live DRF stack to confirm sync moderation is wired up.

Run from GymHubBackend/:
    python manage.py shell < test_sync_moderation.py
"""
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework.test import APIClient

from community.models import Comment, Post
from common.moderation import ModerationStatus

User = get_user_model()

user, _ = User.objects.get_or_create(
    username="syncmodprobe", defaults={"email": "syncmodprobe@example.com"}
)
user.set_password("pw"); user.save()

post, _ = Post.objects.get_or_create(
    author=user,
    title="Sync moderation probe",
    defaults={
        "description": "Probe post",
        "visibility": Post.Visibility.PUBLIC,
        "moderation_status": ModerationStatus.PUBLISHED,
    },
)

client = APIClient(HTTP_HOST="localhost")
client.force_authenticate(user=user)

print("=" * 72)
print("CASE 1: clean comment -> expect 201 + status=published immediately")
print("=" * 72)
url = reverse("post-comments", kwargs={"post_uuid": post.uuid})
resp = client.post(url, {"body": "Great workout, keep it up!"}, format="json")
print(f"  HTTP {resp.status_code}")
print(f"  body: {resp.data}")
if resp.status_code == 201:
    c = Comment.objects.get(uuid=resp.data["uuid"])
    print(f"  DB:  status={c.moderation_status}  moderated_at={c.moderated_at}")

print()
print("=" * 72)
print("CASE 2: harassing comment (Turkish) -> expect 400 + policy message")
print("=" * 72)
resp = client.post(url, {"body": "senin annen bir orospu"}, format="json")
print(f"  HTTP {resp.status_code}")
print(f"  body: {resp.data}")
if resp.status_code == 201:
    print("  !! NOT BLOCKED -- sync moderation didn't run or didn't flag")
else:
    print("  -> Comment was rejected at the API layer (no DB row created).")
    blocked_in_db = Comment.objects.filter(body="senin annen bir orospu").exists()
    print(f"  DB row exists for blocked text? {blocked_in_db} (should be False)")

print()
print("=" * 72)
print("CASE 3: harassing comment (English) -> expect 400")
print("=" * 72)
resp = client.post(url, {"body": "you are a worthless piece of shit"}, format="json")
print(f"  HTTP {resp.status_code}")
print(f"  body: {resp.data}")
