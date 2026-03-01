from rest_framework import serializers
from .models import Exercise , WorkoutSet,WorkoutExercise , Workout , MuscleGroup
from users.serializers import MiniUserProfileSerializer

class MuscleGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = MuscleGroup
        fields = ("id","name","description")

class ExerciseSerializer(serializers.ModelSerializer):
    muscles = MuscleGroupSerializer(many=True,read_only=True)
    class Meta:
        model = Exercise
        fields = ("id","name","description","exercise_type","movement_type","difficulty","muscles","instructions","video_url","equipment_needed","created_at","updated_at")

class WorkoutSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutSet
        fields = ("set_number","reps","weight_unit","weight","duration_seconds")


class WorkoutExerciseSerializer(serializers.ModelSerializer):
    exercise = ExerciseSerializer(read_only=True)
    sets = WorkoutSetSerializer(read_only=True,many=True)
    class Meta:
        model = WorkoutExercise
        fields = ("id","exercise","order","sets","notes")

class WorkoutExerciseWriteSerializer(serializers.ModelSerializer):
    exercise = serializers.PrimaryKeyRelatedField(queryset=Exercise.objects.all())
    sets = WorkoutSetSerializer(many=True)
    class Meta:
        model = WorkoutExercise
        fields = ("exercise","order","sets","notes")

class WorkoutSerializer(serializers.ModelSerializer):
    workout_exercises = WorkoutExerciseSerializer(many=True,read_only=True)
    owner = MiniUserProfileSerializer(source="owner.profile", read_only=True)
    
    class Meta:
        model = Workout
        fields = ("id","owner","name","description","cover_image","workout_exercises","visibility","estimated_duration_min","is_template","created_at","updated_at")

class WorkoutWriteSerializer(serializers.ModelSerializer):
    workout_exercises = WorkoutExerciseWriteSerializer(many=True)
    class Meta:
        model = Workout
        fields = ("id","name","description","cover_image","workout_exercises","visibility","estimated_duration_min","is_template")
    
    def create(self,validated_data):
        workout_exercises_data = validated_data.pop("workout_exercises")
        workout = Workout.objects.create(**validated_data)
        for exercise_data in workout_exercises_data:
            sets_data = exercise_data.pop("sets")
            workout_exercise = WorkoutExercise.objects.create(workout=workout,**exercise_data)
            for set_data in sets_data:
                WorkoutSet.objects.create(workout_exercise=workout_exercise,**set_data)
        return workout
