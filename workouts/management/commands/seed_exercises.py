"""
Idempotent seeder for a starter set of exercises spanning all three categories
(Weightlifting, Calisthenics, Cardio). Safe to re-run: existing rows (matched
by slug) are left alone.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from workouts.models import Exercise, MuscleGroup


WL = Exercise.ExerciseType.WEIGHTLIFTING
CA = Exercise.ExerciseType.CALISTHENICS
CD = Exercise.ExerciseType.CARDIO

COMPOUND = Exercise.MovementType.COMPOUND
ISOMETRIC = Exercise.MovementType.ISOMETRIC
ISOLATION = Exercise.MovementType.ISOLATION

BEG = Exercise.DifficultyLevel.BEGINNER
INT = Exercise.DifficultyLevel.INTERMEDIATE
ADV = Exercise.DifficultyLevel.ADVANCED


def ex(name, type_, movement, diff, equipment, muscles, *, cardio=""):
    return {
        "name": name,
        "exercise_type": type_,
        "movement_type": movement,
        "difficulty": diff,
        "equipment_needed": equipment,
        "muscles": muscles,
        "cardio_intensity": cardio,
    }


EXERCISES = [
    # ── Weightlifting · Push ──
    ex("Barbell Bench Press", WL, COMPOUND, INT, ["barbell", "bench"], ["chest", "triceps", "shoulders"]),
    ex("Incline Dumbbell Press", WL, COMPOUND, INT, ["dumbbell", "bench"], ["chest", "shoulders"]),
    ex("Overhead Press", WL, COMPOUND, INT, ["barbell"], ["shoulders", "triceps"]),
    ex("Dumbbell Lateral Raise", WL, ISOLATION, BEG, ["dumbbell"], ["shoulders"]),
    ex("Cable Triceps Pushdown", WL, ISOLATION, BEG, ["cable"], ["triceps"]),

    # ── Weightlifting · Pull ──
    ex("Barbell Row", WL, COMPOUND, INT, ["barbell"], ["upper-back", "lats", "biceps"]),
    ex("Lat Pulldown", WL, COMPOUND, BEG, ["cable"], ["lats", "biceps"]),
    ex("Dumbbell Curl", WL, ISOLATION, BEG, ["dumbbell"], ["biceps"]),
    ex("Face Pull", WL, ISOLATION, BEG, ["cable"], ["upper-back", "shoulders"]),

    # ── Weightlifting · Legs ──
    ex("Barbell Back Squat", WL, COMPOUND, INT, ["barbell"], ["quads", "glutes"]),
    ex("Romanian Deadlift", WL, COMPOUND, INT, ["barbell"], ["hamstrings", "glutes", "lower-back"]),
    ex("Dumbbell Walking Lunge", WL, COMPOUND, BEG, ["dumbbell"], ["quads", "glutes"]),
    ex("Leg Press", WL, COMPOUND, BEG, ["machine"], ["quads", "glutes"]),
    ex("Standing Calf Raise", WL, ISOLATION, BEG, ["machine"], ["calves"]),

    # ── Calisthenics · Bodyweight ──
    ex("Push-up", CA, COMPOUND, BEG, ["bodyweight"], ["chest", "triceps", "shoulders"]),
    ex("Pull-up", CA, COMPOUND, INT, ["bodyweight"], ["lats", "biceps"]),
    ex("Dip", CA, COMPOUND, INT, ["bodyweight"], ["chest", "triceps"]),
    ex("Bodyweight Squat", CA, COMPOUND, BEG, ["bodyweight"], ["quads", "glutes"]),
    ex("Plank", CA, ISOMETRIC, BEG, ["bodyweight"], ["abs"]),
    ex("Hanging Leg Raise", CA, ISOLATION, INT, ["bodyweight"], ["abs"]),

    # ── Calisthenics · Weighted ──
    ex("Weighted Pull-up", CA, COMPOUND, ADV, ["bodyweight", "dip belt"], ["lats", "biceps"]),
    ex("Weighted Dip", CA, COMPOUND, ADV, ["bodyweight", "dip belt"], ["chest", "triceps"]),
    ex("Weighted Pistol Squat", CA, COMPOUND, ADV, ["bodyweight", "dumbbell"], ["quads", "glutes"]),

    # ── Cardio · LISS ──
    ex("Walking", CD, COMPOUND, BEG, ["bodyweight"], [], cardio="liss"),
    ex("Easy Cycling", CD, COMPOUND, BEG, ["bike"], [], cardio="liss"),

    # ── Cardio · MISS ──
    ex("Steady-State Jog", CD, COMPOUND, BEG, ["bodyweight"], [], cardio="miss"),
    ex("Steady-State Row", CD, COMPOUND, BEG, ["rowing machine"], [], cardio="miss"),

    # ── Cardio · HIIT ──
    ex("Burpees", CD, COMPOUND, INT, ["bodyweight"], [], cardio="hiit"),
    ex("Jump Rope Intervals", CD, COMPOUND, INT, ["jump rope"], [], cardio="hiit"),

    # ── Cardio · SIT ──
    ex("Sprint Intervals", CD, COMPOUND, ADV, ["bodyweight"], [], cardio="sit"),
    ex("Assault Bike Sprints", CD, COMPOUND, ADV, ["assault bike"], [], cardio="sit"),
]


class Command(BaseCommand):
    help = "Seed a starter set of exercises across Weightlifting / Calisthenics / Cardio."

    @transaction.atomic
    def handle(self, *args, **options):
        muscle_by_slug = {m.slug: m for m in MuscleGroup.objects.all()}
        missing_slugs = set()
        created = 0
        skipped = 0

        for spec in EXERCISES:
            slug = slugify(spec["name"])
            obj, was_created = Exercise.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": spec["name"],
                    "exercise_type": spec["exercise_type"],
                    "movement_type": spec["movement_type"],
                    "difficulty": spec["difficulty"],
                    "equipment_needed": spec["equipment_needed"],
                    "cardio_intensity": spec["cardio_intensity"],
                },
            )
            if was_created:
                muscles = []
                for s in spec["muscles"]:
                    m = muscle_by_slug.get(s)
                    if m is None:
                        missing_slugs.add(s)
                    else:
                        muscles.append(m)
                if muscles:
                    obj.muscles.set(muscles)
                created += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created} new exercises ({skipped} already existed)."
        ))
        if missing_slugs:
            self.stdout.write(self.style.WARNING(
                f"Unknown muscle slugs (skipped): {sorted(missing_slugs)}"
            ))
