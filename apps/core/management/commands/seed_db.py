import random
import uuid
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User, JobSeekerProfile
from apps.recruiters.models import RecruiterProfile, Company
from apps.jobs.models import Job, JobCategory, Skill, Qualification, JobContactVisibility

class Command(BaseCommand):
    help = 'Seeds the database with many demo admin, jobseeker, recruiter and demo content.'

    @transaction.atomic
    def handle(self, *args, **kwargs):
        self.stdout.write("Starting bulk database seeding...")

        # 1. Create Admin
        admin_email = "admin@example.com"
        if not User.objects.filter(email=admin_email).exists():
            admin = User.objects.create_superuser(
                email=admin_email,
                password="password123",
                first_name="Super",
                last_name="Admin"
            )
            self.stdout.write(self.style.SUCCESS(f"Created Admin: {admin_email}"))

        # Create basic qualifications and skills
        qual_bed, _ = Qualification.objects.get_or_create(name="B.Ed", slug="b-ed", level=Qualification.Level.BACHELOR)
        qual_med, _ = Qualification.objects.get_or_create(name="M.Ed", slug="m-ed", level=Qualification.Level.MASTER)
        qual_bsc, _ = Qualification.objects.get_or_create(name="B.Sc", slug="b-sc", level=Qualification.Level.BACHELOR)
        qual_msc, _ = Qualification.objects.get_or_create(name="M.Sc", slug="m-sc", level=Qualification.Level.MASTER)
        qual_phd, _ = Qualification.objects.get_or_create(name="Ph.D", slug="ph-d", level=Qualification.Level.DOCTORATE)
        qualifications = [qual_bed, qual_med, qual_bsc, qual_msc, qual_phd]

        categories = ["Teaching", "Administration", "Non-Teaching"]
        category_objs = []
        for c in categories:
            obj, _ = JobCategory.objects.get_or_create(name=c, slug=slugify(c))
            category_objs.append(obj)
            
        subjects = ["Mathematics", "Physics", "Chemistry", "Biology", "English", "Computer Science", "History", "Geography", "Physical Education", "Art", "Music", "Economics"]
        skills = []
        for s in subjects:
            skill, _ = Skill.objects.get_or_create(name=s, slug=slugify(s))
            skills.append(skill)
            
        general_skills = ["Classroom Management", "Curriculum Development", "Student Counseling", "Lesson Planning", "Communication", "Leadership"]
        for s in general_skills:
            skill, _ = Skill.objects.get_or_create(name=s, slug=slugify(s), defaults={'category': Skill.Category.SOFT})
            skills.append(skill)

        # 2. Create Job Seekers
        for i in range(1, 11):
            seeker_email = f"jobseeker{i}@example.com"
            if not User.objects.filter(email=seeker_email).exists():
                seeker = User.objects.create_user(
                    email=seeker_email,
                    password="password123",
                    first_name=f"Seeker",
                    last_name=f"Test{i}",
                    role=User.Role.JOB_SEEKER,
                    is_email_verified=True
                )
                subject = random.choice(subjects)
                JobSeekerProfile.objects.create(
                    user=seeker,
                    headline=f"Experienced {subject} Teacher",
                    summary=f"Passionate {subject} teacher with great experience.",
                    experience_years=random.randint(1, 15),
                    preferred_job_type=random.choice(JobSeekerProfile.JobType.choices)[0]
                )

        self.stdout.write(self.style.SUCCESS("Created 10 Job Seekers"))

        # 3. Create Recruiters and Companies (Schools)
        schools = [
            "Global International School", "Sunrise Academy", "Heritage Public School", 
            "St. Mary's Convent", "Modern High School", "Pinnacle College", 
            "Greenwood High", "Bluebells School", "Apex Institute", "Little Angels Academy"
        ]
        
        locations = ["New Delhi, India", "Mumbai, India", "Bangalore, India", "Chennai, India", "Pune, India", "Hyderabad, India"]
        
        recruiters = []
        companies = []
        
        for i, school_name in enumerate(schools):
            recruiter_email = f"recruiter{i+1}@example.com"
            if not User.objects.filter(email=recruiter_email).exists():
                recruiter_user = User.objects.create_user(
                    email=recruiter_email,
                    password="password123",
                    first_name=f"HR",
                    last_name=f"Manager{i+1}",
                    role=User.Role.RECRUITER,
                    is_email_verified=True
                )
                
                company = Company.objects.create(
                    name=school_name,
                    slug=slugify(school_name + f"-{i}"),
                    industry="Education",
                    website=f"https://{slugify(school_name)}.example.com",
                    location=random.choice(locations),
                    description=f"A top-tier educational institution focusing on holistic development.",
                    is_verified=True,
                    size=random.choice(Company.Size.choices)[0]
                )
                
                rp = RecruiterProfile.objects.create(
                    user=recruiter_user,
                    company=company,
                    designation="HR Manager",
                    phone=f"+919876543{i:03d}"
                )
                recruiters.append(rp)
                companies.append(company)
            else:
                user = User.objects.get(email=recruiter_email)
                rp = RecruiterProfile.objects.get(user=user)
                recruiters.append(rp)
                companies.append(rp.company)

        self.stdout.write(self.style.SUCCESS(f"Created {len(schools)} Recruiters & Schools"))

        # 4. Create Jobs
        job_titles = [
            "{subject} Teacher", "Senior {subject} Lecturer", "Primary {subject} Teacher", 
            "HOD {subject}", "Assistant Professor - {subject}"
        ]
        
        non_teaching_titles = ["Principal", "Vice Principal", "Academic Coordinator", "Librarian", "School Counselor"]
        
        jobs_created = 0
        for _ in range(30):
            rp = random.choice(recruiters)
            company = rp.company
            is_teaching = random.choice([True, True, True, False]) # 75% teaching
            
            if is_teaching:
                subject = random.choice(subjects)
                title = random.choice(job_titles).format(subject=subject)
                cat = category_objs[0] # Teaching
            else:
                title = random.choice(non_teaching_titles)
                cat = category_objs[1] if "Principal" in title or "Coordinator" in title else category_objs[2]
                
            unique_suffix = str(uuid.uuid4())[:8]
            job = Job.objects.create(
                recruiter=rp,
                company=company,
                category=cat,
                title=title,
                slug=slugify(f"{title}-{company.name}-{unique_suffix}"),
                description=f"We are hiring a dedicated {title} to join our wonderful team at {company.name}.",
                location=company.location,
                job_type=random.choice(Job.JobType.choices)[0],
                experience_level=random.choice(Job.ExperienceLevel.choices)[0],
                min_experience_years=random.randint(0, 5),
                salary_min=random.randint(3, 8) * 10000,
                salary_max=random.randint(9, 15) * 10000,
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                is_featured=random.choice([True, False]),
                minimum_qualification=random.choice(qualifications),
                deadline=timezone.now().date() + timezone.timedelta(days=random.randint(15, 60)),
                published_at=timezone.now() - timezone.timedelta(days=random.randint(0, 10))
            )
            
            job.skills_required.add(*random.sample(skills, k=random.randint(2, 5)))
            job.preferred_qualifications.add(*random.sample(qualifications, k=random.randint(1, 3)))
            
            JobContactVisibility.objects.create(
                job=job,
                state=JobContactVisibility.State.AUTO,
                expires_at=timezone.now() + timezone.timedelta(days=30)
            )
            jobs_created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {jobs_created} Demo Jobs"))

        self.stdout.write(self.style.SUCCESS("Database seeded successfully with bulk data!"))
        self.stdout.write(self.style.WARNING("Admin: admin@example.com / password123"))
        self.stdout.write(self.style.WARNING("Job Seekers: jobseeker1@example.com to jobseeker10@example.com / password123"))
        self.stdout.write(self.style.WARNING("Recruiters: recruiter1@example.com to recruiter10@example.com / password123"))
