from rest_framework import serializers
from .models import (
    TeacherProfile, EducationDetail, TeacherCertification, 
    TeachingExperience, TeacherSkill, TeacherLanguage, 
    TeacherDocument, TeachingApplication
)

class EducationDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = EducationDetail
        exclude = ["profile"]

class TeacherCertificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherCertification
        exclude = ["profile"]

class TeachingExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeachingExperience
        exclude = ["profile"]

class TeacherSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherSkill
        exclude = ["profile"]

class TeacherLanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherLanguage
        exclude = ["profile"]

class TeacherDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherDocument
        exclude = ["profile"]

class TeacherProfileSerializer(serializers.ModelSerializer):
    education_details = EducationDetailSerializer(many=True, read_only=True)
    certifications = TeacherCertificationSerializer(many=True, read_only=True)
    experiences = TeachingExperienceSerializer(many=True, read_only=True)
    skills = TeacherSkillSerializer(many=True, read_only=True)
    languages = TeacherLanguageSerializer(many=True, read_only=True)
    documents = TeacherDocumentSerializer(many=True, read_only=True)
    
    class Meta:
        model = TeacherProfile
        exclude = ["user"]

    def validate_mobile_number(self, value):
        if not value.isdigit() or len(value) < 10:
            raise serializers.ValidationError("Mobile number must be valid.")
        return value

class TeachingApplicationSerializer(serializers.ModelSerializer):
    profile_summary = TeacherProfileSerializer(source='profile', read_only=True)
    
    class Meta:
        model = TeachingApplication
        fields = "__all__"
        read_only_fields = ["status", "employer_notes", "profile", "job"]

class EmployerApplicationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeachingApplication
        fields = ["status", "employer_notes"]
