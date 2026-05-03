"""
Idempotent seeder for the Locust load-test fixture.

Creates `--users` synthetic accounts (`loadtest_user_<i>` / password `loadtestpw123!`),
a sparse follow graph (each user follows ~20 random others, accepted), `--posts-per-user`
PUBLISHED posts per user, and a handful of comments. Bypasses the moderation pipeline
by writing `moderation_status=PUBLISHED` directly via the ORM.

Writes `loadtest/fixtures.json` next to the project root with the credentials
and content UUIDs that the locustfile reads at startup.

Re-running is safe: existing accounts are reused, additional posts are not created
beyond the requested count.
"""
import json
import random
import uuid as uuid_mod
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from common.moderation import ModerationStatus
from community.models import Comment, Post
from users.models import UserFollower, UserProfile

User = get_user_model()

PASSWORD = "loadtestpw123!"
USERNAME_PREFIX = "loadtest_user_"


class Command(BaseCommand):
    help = "Seed users, posts, follows, comments for the Locust load test."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=300)
        parser.add_argument("--posts-per-user", type=int, default=8)
        parser.add_argument("--follows-per-user", type=int, default=20)
        parser.add_argument("--comments-per-post", type=int, default=2)
        parser.add_argument(
            "--out",
            type=str,
            # parents[3] = GymHubBackend/ (this file lives at common/management/commands/)
            default=str(Path(__file__).resolve().parents[3] / "loadtest" / "fixtures.json"),
        )

    def handle(self, *args, **opts):
        n_users = opts["users"]
        posts_per_user = opts["posts_per_user"]
        follows_per_user = opts["follows_per_user"]
        comments_per_post = opts["comments_per_post"]
        out_path = Path(opts["out"])

        self.stdout.write(f"Seeding {n_users} users...")
        users = self._seed_users(n_users)

        self.stdout.write(f"Seeding follow graph (~{follows_per_user}/user)...")
        self._seed_follows(users, follows_per_user)

        self.stdout.write(f"Seeding {posts_per_user} posts per user...")
        post_uuids = self._seed_posts(users, posts_per_user)

        self.stdout.write(f"Seeding {comments_per_post} comments per post...")
        self._seed_comments(users, post_uuids, comments_per_post)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        fixture = {
            "password": PASSWORD,
            "users": [{"username": u.username, "uuid": str(u.uuid)} for u in users],
            "post_uuids": [str(p) for p in post_uuids],
        }
        out_path.write_text(json.dumps(fixture, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {out_path} ({len(users)} users, {len(post_uuids)} posts)"
        ))

    def _seed_users(self, n):
        existing = {u.username: u for u in User.objects.filter(username__startswith=USERNAME_PREFIX)}
        users = []
        for i in range(n):
            username = f"{USERNAME_PREFIX}{i}"
            user = existing.get(username)
            if user is None:
                # create_user fires post_save -> on_commit profile creation;
                # one transaction per user keeps that callback firing immediately.
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username,
                        email=f"{username}@loadtest.local",
                        password=PASSWORD,
                    )
            users.append(user)
        # Backfill any missing profiles (in case on_commit didn't run e.g. inside an outer txn).
        for u in users:
            UserProfile.objects.get_or_create(user=u)
        return users

    def _seed_follows(self, users, per_user):
        rng = random.Random(42)
        existing_pairs = set(
            UserFollower.objects.filter(from_user__in=users)
            .values_list("from_user_id", "to_user_id")
        )
        to_create = []
        for u in users:
            candidates = [c for c in users if c.id != u.id]
            picks = rng.sample(candidates, min(per_user, len(candidates)))
            for target in picks:
                if (u.id, target.id) in existing_pairs:
                    continue
                to_create.append(UserFollower(
                    from_user=u,
                    to_user=target,
                    status=UserFollower.FollowStatus.ACCEPTED,
                ))
        if to_create:
            UserFollower.objects.bulk_create(to_create, batch_size=1000, ignore_conflicts=True)
            # Counter denorm: bump followers/following counts in a single pass.
            from django.db.models import Count
            from_counts = dict(
                UserFollower.objects.filter(status=UserFollower.FollowStatus.ACCEPTED)
                .values("from_user").annotate(c=Count("id")).values_list("from_user", "c")
            )
            to_counts = dict(
                UserFollower.objects.filter(status=UserFollower.FollowStatus.ACCEPTED)
                .values("to_user").annotate(c=Count("id")).values_list("to_user", "c")
            )
            for u in users:
                UserProfile.objects.filter(user_id=u.id).update(
                    following_count=from_counts.get(u.id, 0),
                    followers_count=to_counts.get(u.id, 0),
                )

    def _seed_posts(self, users, per_user):
        rng = random.Random(7)
        from django.db.models import Count
        # Reuse posts already authored by these users; only create the delta.
        existing_counts = dict(
            Post.objects.filter(author__in=users, is_deleted=False)
            .values("author").annotate(c=Count("id")).values_list("author", "c")
        )
        to_create = []
        for u in users:
            already = existing_counts.get(u.id, 0)
            need = max(0, per_user - already)
            for _ in range(need):
                # bulk_create skips Post.save(), so the auto-slug never fires;
                # pre-populate with a unique value to avoid collisions.
                slug_token = uuid_mod.uuid4().hex[:16]
                to_create.append(Post(
                    author=u,
                    title=f"Loadtest post by {u.username} #{rng.randint(0, 10**6)}",
                    slug=f"lt-{u.username}-{slug_token}",
                    description=f"Synthetic content for load testing. lorem ipsum {rng.random()}",
                    post_type=Post.PostType.GENERAL,
                    visibility=Post.Visibility.PUBLIC,
                    moderation_status=ModerationStatus.PUBLISHED,
                ))
        if to_create:
            Post.objects.bulk_create(to_create, batch_size=500)
        return list(
            Post.objects.filter(author__in=users, moderation_status=ModerationStatus.PUBLISHED)
            .values_list("uuid", flat=True)
        )

    def _seed_comments(self, users, post_uuids, per_post):
        rng = random.Random(13)
        from django.db.models import Count
        # Skip if posts already have enough comments — keeps re-runs cheap.
        post_objs = list(Post.objects.filter(uuid__in=post_uuids).only("id", "uuid"))
        existing = dict(
            Comment.objects.filter(post__in=post_objs)
            .values("post").annotate(c=Count("id")).values_list("post", "c")
        )
        to_create = []
        for p in post_objs:
            need = max(0, per_post - existing.get(p.id, 0))
            for _ in range(need):
                author = rng.choice(users)
                to_create.append(Comment(
                    post=p,
                    author=author,
                    body=f"Seed comment #{rng.randint(0, 10**6)}",
                    moderation_status=ModerationStatus.PUBLISHED,
                ))
        if to_create:
            Comment.objects.bulk_create(to_create, batch_size=1000)
