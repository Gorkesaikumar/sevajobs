from django.db import models
from django.conf import settings
from apps.core.models import BaseModel
from apps.jobs.models import Job

class TeacherProfile(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teacher_profile")
    
    # Personal Information
    mobile_number = models.CharField(max_length=20)
    alternate_mobile = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    
    current_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pin_code = models.CharField(max_length=10, blank=True)
    nationality = models.CharField(max_length=50, default="Indian")
    
    # Professional Information
    class ApplyingPosition(models.TextChoices):
        PRT = "prt", "Primary Teacher (PRT)"
        TGT = "tgt", "Trained Graduate Teacher (TGT)"
        PGT = "pgt", "Post Graduate Teacher (PGT)"
        LECTURER = "lecturer", "Lecturer"
        ASSISTANT_PROFESSOR = "assistant_professor", "Assistant Professor"
        PROFESSOR = "professor", "Professor"
        PRINCIPAL = "principal", "Principal"
        OTHER = "other", "Other"
    
    applying_position = models.CharField(max_length=30, choices=ApplyingPosition.choices)
    subject_specialization = models.CharField(max_length=100)
    total_experience_years = models.DecimalField(max_digits=4, decimal_places=1, default=0.0)
    
    current_employer = models.CharField(max_length=150, blank=True)
    current_designation = models.CharField(max_length=100, blank=True)
    current_salary = models.PositiveIntegerField(null=True, blank=True)
    expected_salary = models.PositiveIntegerField(null=True, blank=True)
    notice_period_days = models.PositiveSmallIntegerField(default=0)
    immediate_joining = models.BooleanField(default=False)
    
    # Additional Information
    career_objective = models.TextField(blank=True)
    why_join_us = models.TextField(blank=True)
    achievements = models.TextField(blank=True)
    awards_recognition = models.TextField(blank=True)
    research_publications = models.TextField(blank=True)
    references = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_applying_position_display()}"


class EducationDetail(BaseModel):
    profile = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="education_details")
    
    class QualificationLevel(models.TextChoices):
        TENTH = "10th", "10th"
        TWELFTH = "12th", "12th"
        DIPLOMA = "diploma", "Diploma"
        GRADUATION = "graduation", "Graduation"
        POST_GRADUATION = "post_graduation", "Post Graduation"
        PHD = "phd", "PhD"
        OTHER = "other", "Other Certifications"
        
    qualification = models.CharField(max_length=20, choices=QualificationLevel.choices)
    institution_name = models.CharField(max_length=200)
    board_university = models.CharField(max_length=200)
    year_of_passing = models.PositiveIntegerField()
    percentage_cgpa = models.CharField(max_length=10)

    class Meta(BaseModel.Meta):
        ordering = ["-year_of_passing"]


class TeacherCertification(BaseModel):
    profile = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="certifications")
    
    class CertType(models.TextChoices):
        B_ED = "b_ed", "B.Ed"
        D_ED = "d_ed", "D.Ed"
        M_ED = "m_ed", "M.Ed"
        CTET = "ctet", "CTET"
        TET = "tet", "TET"
        NET = "net", "NET"
        SET = "set", "SET"
        MONTESSORI = "montessori", "Montessori Certification"
        OTHER = "other", "Other Professional Certifications"
        
    certification_name = models.CharField(max_length=30, choices=CertType.choices)
    year_obtained = models.PositiveIntegerField(null=True, blank=True)
    authority = models.CharField(max_length=150, blank=True)


class TeachingExperience(BaseModel):
    profile = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="experiences")
    institution_name = models.CharField(max_length=200)
    designation = models.CharField(max_length=100)
    subject_taught = models.CharField(max_length=100)
    
    class EmpType(models.TextChoices):
        FULL_TIME = "full_time", "Full Time"
        PART_TIME = "part_time", "Part Time"
        CONTRACT = "contract", "Contract"
        GUEST = "guest", "Guest Faculty"
        
    employment_type = models.CharField(max_length=20, choices=EmpType.choices, default=EmpType.FULL_TIME)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    currently_working = models.BooleanField(default=False)
    roles_and_responsibilities = models.TextField(blank=True)
    
    class Meta(BaseModel.Meta):
        ordering = ["-start_date"]


class TeacherSkill(BaseModel):
    profile = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="skills")
    
    class SkillType(models.TextChoices):
        CLASSROOM_MANAGEMENT = "classroom_management", "Classroom Management"
        LESSON_PLANNING = "lesson_planning", "Lesson Planning"
        CURRICULUM_DEV = "curriculum_development", "Curriculum Development"
        ONLINE_TEACHING = "online_teaching", "Online Teaching"
        SMART_BOARD = "smart_board", "Smart Board Usage"
        GOOGLE_CLASSROOM = "google_classroom", "Google Classroom"
        ZOOM = "zoom", "Zoom"
        MS_TEAMS = "ms_teams", "Microsoft Teams"
        STUDENT_ASSESSMENT = "student_assessment", "Student Assessment"
        PARENT_COMM = "parent_communication", "Parent Communication"
        OTHER = "other", "Other Skills"
        
    skill_name = models.CharField(max_length=40, choices=SkillType.choices)


class TeacherLanguage(BaseModel):
    profile = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="languages")
    language_name = models.CharField(max_length=50)
    can_read = models.BooleanField(default=True)
    can_write = models.BooleanField(default=True)
    can_speak = models.BooleanField(default=True)


class TeacherDocument(BaseModel):
    profile = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="documents")
    
    class DocType(models.TextChoices):
        RESUME = "resume", "Resume (PDF)"
        PHOTO = "photo", "Passport Photo"
        EDUCATION = "education_cert", "Educational Certificates"
        EXPERIENCE = "experience_cert", "Experience Certificates"
        CERTIFICATION = "teaching_cert", "Teaching Certifications"
        ADDITIONAL = "additional", "Additional Documents"
        
    document_type = models.CharField(max_length=30, choices=DocType.choices)
    file = models.FileField(upload_to="teacher_docs/%Y/%m/")
    uploaded_at = models.DateTimeField(auto_now_add=True)


class TeachingApplication(BaseModel):
    profile = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="applications")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="teaching_applications")
    
    # Screening Questions
    years_experience_subject = models.DecimalField(max_digits=4, decimal_places=1, default=0.0)
    can_teach_online = models.BooleanField(default=False)
    willing_to_relocate = models.BooleanField(default=False)
    english_medium_instruction = models.BooleanField(default=False)
    expected_joining_date = models.DateField(null=True, blank=True)
    
    # Employer Features
    class AppStatus(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"
        SHORTLISTED = "shortlisted", "Shortlisted"
        INTERVIEW_SCHEDULED = "interview_scheduled", "Interview Scheduled"
        REJECTED = "rejected", "Rejected"
        HIRED = "hired", "Hired"
        
    status = models.CharField(max_length=30, choices=AppStatus.choices, default=AppStatus.SUBMITTED)
    employer_notes = models.TextField(blank=True)
    
    class Meta(BaseModel.Meta):
        unique_together = ("profile", "job")
