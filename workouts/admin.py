from django.contrib import admin

from .models import Exercise, MuscleGroup, Workout, WorkoutExercise


class WorkoutExerciseInline(admin.TabularInline):
    model = WorkoutExercise
    extra = 1
    fields = ("order", "exercise", "sets", "reps", "weight_kg", "duration_sec", "rest_sec", "notes")
    ordering = ("order",)


@admin.register(MuscleGroup)
class MuscleGroupAdmin(admin.ModelAdmin):
    list_display  = ("name",)
    search_fields = ("name",)


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display   = ("name", "exercise_type", "movement_type", "difficulty", "created_at")
    list_filter    = ("exercise_type", "movement_type", "difficulty")
    search_fields  = ("name", "description")
    filter_horizontal = ("muscles",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Basic Info", {"fields": ("name", "description", "instructions", "video_url", "equipment_needed")}),
        ("Classification", {"fields": ("exercise_type", "movement_type", "difficulty")}),
        ("Muscles", {"fields": ("muscles",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Workout)
class WorkoutAdmin(admin.ModelAdmin):
    list_display   = ("name", "owner", "visibility", "is_template", "exercise_count", "created_at")
    list_filter    = ("visibility", "is_template")
    search_fields  = ("name", "description", "owner__username")
    readonly_fields = ("created_at", "updated_at")
    inlines        = [WorkoutExerciseInline]
    fieldsets = (
        ("Info", {"fields": ("owner", "name", "description", "cover_image")}),
        ("Settings", {"fields": ("visibility", "estimated_duration_min", "is_template")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
