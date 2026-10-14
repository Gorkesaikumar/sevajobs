"""
Canonical, production-ready default email templates for candidate recruitment workflows.
Mapped strictly to authoritative status choices:
- Shortlisted
- Interviewing (interview_scheduled)
- Selected
- Joined
- Rejected
- General Eligible
"""

from typing import Dict, Any

CANONICAL_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "shortlisted": {
        "name": "Shortlisted Candidates Default",
        "subject": "Application Update: You have been shortlisted for {{ requirement_title }} at {{ school_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>Great news! We are pleased to inform you that your profile has been <strong>shortlisted</strong> for the <strong>{{ requirement_title }}</strong> opening at <strong>{{ school_name }}</strong> in {{ location }}.</p>

<p>Our academic recruitment committee was impressed with your qualifications and experience.</p>

<h4 style="color: #1e293b; margin-top: 20px;">Next Steps in the Selection Process:</h4>
<ul>
    <li>Our recruitment team will review scheduling availability for an introductory interview.</li>
    <li>Please ensure your contact details, resume, and subject credentials on your SevaJobs profile are up to date.</li>
    <li>If you have specific time slots or demo presentation materials to share, you may reply directly to this email.</li>
</ul>

<p>We look forward to speaking with you soon and guiding you through the next round.</p>

<p>Warm regards,<br>
<strong>{{ school_name }} Recruitment Team</strong><br>
via SevaJobs Platform</p>""",
        "body_plain": """Dear {{ candidate_name }},

Great news! We are pleased to inform you that your profile has been shortlisted for the {{ requirement_title }} opening at {{ school_name }} in {{ location }}.

Our academic recruitment committee was impressed with your qualifications and experience.

Next Steps in the Selection Process:
- Our recruitment team will review scheduling availability for an introductory interview.
- Please ensure your contact details, resume, and subject credentials on your SevaJobs profile are up to date.
- If you have specific time slots or demo presentation materials to share, you may reply directly to this email.

We look forward to speaking with you soon!

Warm regards,
{{ school_name }} Recruitment Team
via SevaJobs Platform""",
    },

    "interviewing": {
        "name": "Interviewing Candidates Default",
        "subject": "Interview Scheduled / In Progress: {{ requirement_title }} at {{ school_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>This is an important update regarding your interview process for the <strong>{{ requirement_title }}</strong> position at <strong>{{ school_name }}</strong> in {{ location }}.</p>

<p>Your current recruitment status is: <strong>{{ candidate_status }}</strong>.</p>

<h4 style="color: #1e293b; margin-top: 20px;">Interview Preparation & Guidelines:</h4>
<ul>
    <li>Please have your educational certificates and teaching credentials readily accessible.</li>
    <li>Be prepared for a demo teaching session or subject matter pedagogy discussion as advised by the academic panel.</li>
    <li>If your interview is online, please ensure a stable internet connection, working webcam, and quiet environment.</li>
    <li>If in-person, please arrive at the institution campus 15 minutes prior to the scheduled slot.</li>
</ul>

<p>If you need to reschedule or require any accommodation, please reply to this message as early as possible.</p>

<p>We wish you the very best for your interview!</p>

<p>Warm regards,<br>
<strong>{{ school_name }} Academic Panel</strong><br>
via SevaJobs Platform</p>""",
        "body_plain": """Dear {{ candidate_name }},

This is an important update regarding your interview process for the {{ requirement_title }} position at {{ school_name }} in {{ location }}.

Your current recruitment status is: {{ candidate_status }}.

Interview Preparation & Guidelines:
- Please have your educational certificates and teaching credentials readily accessible.
- Be prepared for a demo teaching session or subject matter pedagogy discussion as advised by the academic panel.
- If your interview is online, please ensure a stable internet connection, working webcam, and quiet environment.
- If in-person, please arrive at the campus 15 minutes prior to the scheduled slot.

If you need to reschedule or require any accommodation, please reply to this message as early as possible.

We wish you the very best for your interview!

Warm regards,
{{ school_name }} Academic Panel
via SevaJobs Platform""",
    },

    "selected": {
        "name": "Selected Candidates Default",
        "subject": "Congratulations! Offer of Selection for {{ requirement_title }} at {{ school_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>Congratulations! We are delighted to inform you that you have been <strong>selected</strong> for the <strong>{{ requirement_title }}</strong> faculty position at <strong>{{ school_name }}</strong> in {{ location }}.</p>

<p>The academic panel was thoroughly impressed by your subject knowledge, educational philosophy, and pedagogical expertise.</p>

<h4 style="color: #1e293b; margin-top: 20px;">Offer & Onboarding Next Steps:</h4>
<ul>
    <li>Our administration team will follow up shortly with your formal offer letter and compensation schedule.</li>
    <li>Please review the onboarding documentation checklist sent to your registered email.</li>
    <li>Kindly confirm your acceptance and anticipated joining date by replying to this message.</li>
</ul>

<p>We are thrilled about the prospect of welcoming you to our faculty team and shaping young minds together!</p>

<p>Warm regards,<br>
<strong>{{ school_name }} Management &amp; HR</strong><br>
via SevaJobs Platform</p>""",
        "body_plain": """Dear {{ candidate_name }},

Congratulations! We are delighted to inform you that you have been selected for the {{ requirement_title }} faculty position at {{ school_name }} in {{ location }}.

The academic panel was thoroughly impressed by your subject knowledge, educational philosophy, and pedagogical expertise.

Offer & Onboarding Next Steps:
- Our administration team will follow up shortly with your formal offer letter and compensation schedule.
- Please review the onboarding documentation checklist sent to your registered email.
- Kindly confirm your acceptance and anticipated joining date by replying to this message.

We are thrilled about the prospect of welcoming you to our faculty team!

Warm regards,
{{ school_name }} Management & HR
via SevaJobs Platform""",
    },

    "joined": {
        "name": "Joined Candidates Default",
        "subject": "Welcome to the Faculty! Joining Information for {{ school_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>Welcome to <strong>{{ school_name }}</strong>! We are thrilled to officially welcome you as our <strong>{{ requirement_title }}</strong> educator in {{ location }}.</p>

<p>Your recruitment outcome is officially recorded as <strong>Joined</strong> on SevaJobs.</p>

<h4 style="color: #1e293b; margin-top: 20px;">Faculty Orientation &amp; Onboarding:</h4>
<ul>
    <li>Report to the administrative office on your scheduled orientation day for badge issuance.</li>
    <li>Submit original verification copies of your degrees, B.Ed/M.Sc certificates, and identification proof.</li>
    <li>Meet your department head and collect your curriculum syllabus and academic calendar.</li>
</ul>

<p>Should you need any support prior to your start date, do not hesitate to contact our administrative desk.</p>

<p>Wishing you an inspiring, rewarding, and impactful teaching journey with us!</p>

<p>Warm regards,<br>
<strong>Administration &amp; Faculty HR</strong><br>
{{ school_name }}</p>""",
        "body_plain": """Dear {{ candidate_name }},

Welcome to {{ school_name }}! We are thrilled to officially welcome you as our {{ requirement_title }} educator in {{ location }}.

Your recruitment outcome is officially recorded as Joined on SevaJobs.

Faculty Orientation & Onboarding:
- Report to the administrative office on your scheduled orientation day for badge issuance.
- Submit original verification copies of your degrees, B.Ed/M.Sc certificates, and identification proof.
- Meet your department head and collect your curriculum syllabus and academic calendar.

Should you need any support prior to your start date, do not hesitate to contact our administrative desk.

Wishing you an inspiring and rewarding teaching journey with us!

Warm regards,
Administration & Faculty HR
{{ school_name }}""",
    },

    "rejected": {
        "name": "Rejected Candidates Default",
        "subject": "Update regarding your application for {{ requirement_title }} at {{ school_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>Thank you for your interest in the <strong>{{ requirement_title }}</strong> position at <strong>{{ school_name }}</strong> and for taking the time to participate in our recruitment process.</p>

<p>After thorough review and consideration of all candidates against our current staffing requirements, we regret to inform you that we will not be moving forward with your candidacy for this particular vacancy.</p>

<p>We received applications from many exceptionally qualified educators, making this a difficult decision. Please note that we have retained your profile in our SevaJobs active educator pool and will notify you when new teaching opportunities matching your specialization become available.</p>

<p>We genuinely appreciate the effort you invested and wish you every success in your academic and professional endeavors.</p>

<p>Sincerely,<br>
<strong>Academic Selection Committee</strong><br>
{{ school_name }}</p>""",
        "body_plain": """Dear {{ candidate_name }},

Thank you for your interest in the {{ requirement_title }} position at {{ school_name }} and for taking the time to participate in our recruitment process.

After thorough review and consideration of all candidates against our current staffing requirements, we regret to inform you that we will not be moving forward with your candidacy for this particular vacancy.

We received applications from many exceptionally qualified educators, making this a difficult decision. Please note that we have retained your profile in our SevaJobs active educator pool and will notify you when new teaching opportunities matching your specialization become available.

We genuinely appreciate the effort you invested and wish you every success in your academic career.

Sincerely,
Academic Selection Committee
{{ school_name }}""",
    },

    "general": {
        "name": "General Eligible Candidates Default",
        "subject": "Recruitment Update: {{ requirement_title }} at {{ school_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>We are reaching out with an update regarding the <strong>{{ requirement_title }}</strong> opening at <strong>{{ school_name }}</strong> in {{ location }}.</p>

<p>Your current recruitment status for this position is: <strong>{{ candidate_status }}</strong>.</p>

<p>Our academic recruitment committee is actively reviewing candidate profiles. If you are selected for an interview or further discussion, you will receive full scheduling instructions directly via email and on your candidate portal.</p>

<p>Please ensure that your teaching experience, degree certifications, and contact phone number on your SevaJobs profile remain up to date.</p>

<p>If you have any questions regarding your application or have updated your availability, please feel free to reply directly to this message.</p>

<p>Warm regards,<br>
<strong>SevaJobs Recruitment Team</strong><br>
on behalf of {{ school_name }}</p>""",
        "body_plain": """Dear {{ candidate_name }},

We are reaching out with an update regarding the {{ requirement_title }} opening at {{ school_name }} in {{ location }}.

Your current recruitment status for this position is: {{ candidate_status }}.

Our academic recruitment committee is actively reviewing candidate profiles. If you are selected for an interview or further discussion, you will receive full scheduling instructions directly via email and on your candidate portal.

Please ensure that your teaching experience, degree certifications, and contact phone number on your SevaJobs profile remain up to date.

If you have any questions regarding your application or have updated your availability, please feel free to reply directly to this message.

Warm regards,
SevaJobs Recruitment Team
on behalf of {{ school_name }}""",
    },
}

DEFAULT_JOB_ALERT_TEMPLATE: Dict[str, Any] = {
    "name": "Daily Job Alert (General)",
    "subject": "New Job Vacancies Matching Your Profile — SevaJobs Alert",
    "body_html": """<p>Dear {{ candidate_name }},</p>

<p>Based on your professional profile as <strong>{{ candidate_profession }}</strong> (Subject: <strong>{{ candidate_subject }}</strong>), we identified new, verified job opportunities on SevaJobs that match your qualifications and preferences:</p>

<div style="margin: 20px 0;">
{{ matching_jobs }}
</div>

<p>We encourage you to review and apply promptly as institutions review applications on an ongoing basis.</p>

<p>Wishing you success in your career journey,</p>

<p>Warm regards,<br>
<strong>The SevaJobs Career Team</strong><br>
<a href="https://sevajobs.in" style="color: #4f46e5; text-decoration: none;">www.sevajobs.in</a></p>""",
    "body_plain": """Dear {{ candidate_name }},

Based on your professional profile as {{ candidate_profession }} (Subject: {{ candidate_subject }}), we identified new, verified job opportunities on SevaJobs that match your qualifications and preferences:

{{ matching_jobs }}

We encourage you to review and apply promptly as institutions review applications on an ongoing basis.

Warm regards,
The SevaJobs Career Team
www.sevajobs.in""",
}

FIVE_ALERT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "daily_digest": DEFAULT_JOB_ALERT_TEMPLATE,

    "interview_alert": {
        "name": "Interview & Shortlisting Alert (Personal)",
        "subject": "Recruitment Status Update: {{ candidate_status }} for {{ role_title }} at {{ institution_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>We have an important recruitment update regarding your candidacy for <strong>{{ role_title }}</strong> at <strong>{{ institution_name }}</strong>.</p>

<div style="background-color: #f8fafc; border-left: 4px solid #4f46e5; padding: 16px 20px; margin: 18px 0; border-radius: 4px;">
  <p style="margin: 0 0 8px 0;"><strong>Recruitment Status:</strong> <span style="color: #4f46e5; font-weight: 700;">{{ candidate_status }}</span></p>
  {{ interview_details_block }}
</div>

<p><strong>Next Steps:</strong></p>
<p>{{ next_steps }}</p>

<p>Please log in to your SevaJobs candidate dashboard to view complete timeline details and communicate with the academic recruitment team.</p>

<p>Wishing you every success in the selection process,</p>

<p>Warm regards,<br>
<strong>{{ institution_name }} Academic Panel</strong><br>
via SevaJobs Career Platform</p>""",
        "body_plain": """Dear {{ candidate_name }},

We have an important recruitment update regarding your candidacy for {{ role_title }} at {{ institution_name }}.

Current Status: {{ candidate_status }}
{{ interview_details_plain }}

Next Steps:
{{ next_steps }}

Please log in to your SevaJobs dashboard for full details.

Warm regards,
{{ institution_name }} Academic Panel
via SevaJobs Career Platform""",
    },

    "walkin_alert": {
        "name": "Urgent Walk-in Interview Alert",
        "subject": "Walk-in Interview Notice: {{ role_title }} at {{ institution_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>An urgent <strong>Walk-in Interview</strong> has been scheduled for the role of <strong>{{ role_title }}</strong> at <strong>{{ institution_name }}</strong>, matching your background in <strong>{{ candidate_subject }}</strong>.</p>

<div style="background-color: #fef2f2; border: 1px solid #fecaca; padding: 18px 20px; margin: 18px 0; border-radius: 8px;">
  <h4 style="color: #991b1b; margin: 0 0 12px 0;">Official Walk-in Event Details</h4>
  <p style="margin: 0 0 6px 0;"><strong>Role:</strong> {{ role_title }}</p>
  <p style="margin: 0 0 6px 0;"><strong>Institution:</strong> {{ institution_name }}</p>
  <p style="margin: 0 0 6px 0;"><strong>Date & Time:</strong> {{ walkin_dates_and_time }}</p>
  <p style="margin: 0 0 6px 0;"><strong>Venue Location:</strong> {{ walkin_venue }}</p>
  <p style="margin: 0;"><strong>Attendance Note:</strong> {{ walkin_attendance_note }}</p>
</div>

<p><strong>Required Documents & Instructions:</strong></p>
<p>{{ walkin_instructions }}</p>

<div style="margin: 20px 0;">
  <a href="{{ walkin_job_url }}" style="background-color: #dc2626; color: #ffffff; padding: 10px 22px; text-decoration: none; border-radius: 6px; font-weight: 700; display: inline-block;">View Official Walk-in Notice</a>
</div>

<p>Warm regards,<br>
<strong>SevaJobs Urgent Alerts Team</strong></p>""",
        "body_plain": """Dear {{ candidate_name }},

An urgent Walk-in Interview has been scheduled for {{ role_title }} at {{ institution_name }}, matching your specialization in {{ candidate_subject }}.

Walk-in Event Details:
- Role: {{ role_title }}
- Institution: {{ institution_name }}
- Date & Time: {{ walkin_dates_and_time }}
- Venue: {{ walkin_venue }}
- Note: {{ walkin_attendance_note }}

Instructions & Documents to Bring:
{{ walkin_instructions }}

View Official Notice: {{ walkin_job_url }}

Warm regards,
SevaJobs Urgent Alerts Team""",
    },

    "employer_alert": {
        "name": "Employer Fast Hiring & Outreach Alert",
        "subject": "Source Verified Educators for {{ company_name }} — SevaJobs Institutional Hiring",
        "body_html": """<p>Dear {{ employer_contact_name }},</p>

<p>Greetings from SevaJobs — India's dedicated educator recruitment platform connecting schools, colleges, and academic institutions with verified teaching professionals.</p>

<p>As you plan faculty and staffing requirements for <strong>{{ company_name }}</strong>, we invite you to explore our two fast-track hiring workflows:</p>

<div style="margin: 20px 0;">
  <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
    <h4 style="margin: 0 0 6px 0; color: #1e293b;">1. Post a Teaching Job Posting</h4>
    <p style="font-size: 14px; color: #64748b; margin-bottom: 10px;">Publish full-time, part-time, or walk-in teaching opportunities directly to our active database of qualified educators.</p>
    <a href="{{ post_job_url }}" style="background-color: #4f46e5; color: #ffffff; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600; display: inline-block;">Post a Teaching Vacancy &rarr;</a>
  </div>
  <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px;">
    <h4 style="margin: 0 0 6px 0; color: #1e293b;">2. Fast Institutional Requirement (&lt;30 Seconds)</h4>
    <p style="font-size: 14px; color: #64748b; margin-bottom: 10px;">Need urgent faculty? Submit your teaching grade and subject criteria and our matching system surfaces matching candidates immediately.</p>
    <a href="{{ submit_requirement_url }}" style="background-color: #059669; color: #ffffff; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600; display: inline-block;">Submit Teaching Requirement &rarr;</a>
  </div>
</div>

<p>Our academic recruitment specialists are available to support your staffing initiatives.</p>

<p>Warm regards,<br>
<strong>The SevaJobs Institutional Partnerships Team</strong><br>
<a href="https://sevajobs.in" style="color: #4f46e5; text-decoration: none;">www.sevajobs.in</a></p>""",
        "body_plain": """Dear {{ employer_contact_name }},

Greetings from SevaJobs — India's dedicated educator recruitment platform connecting schools, colleges, and academic institutions with verified teaching professionals.

For your staffing needs at {{ company_name }}, explore our two hiring workflows:

1. Post a Teaching Vacancy:
{{ post_job_url }}

2. Submit an Institutional Requirement (<30 seconds):
{{ submit_requirement_url }}

Warm regards,
The SevaJobs Institutional Partnerships Team
www.sevajobs.in""",
    },

    "requirement_alert": {
        "name": "VIP Urgent Requirement Alert",
        "subject": "VIP Urgent Opening: {{ requirement_subject }} ({{ requirement_grade }}) at {{ institution_name }}",
        "body_html": """<p>Dear {{ candidate_name }},</p>

<p>A new, priority institutional teaching requirement has just been approved on SevaJobs matching your profile in <strong>{{ candidate_subject }}</strong>:</p>

<div style="background-color: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 20px; margin: 18px 0;">
  <div style="display: inline-block; background-color: #1e40af; color: #ffffff; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; text-transform: uppercase; margin-bottom: 8px;">VIP Urgent Requirement</div>
  <h3 style="margin: 0 0 10px 0; color: #1e3a8a;">{{ requirement_subject }} ({{ requirement_grade }})</h3>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Institution:</strong> {{ institution_name }}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {{ requirement_location }}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Experience Needed:</strong> {{ requirement_experience }}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Offered Remuneration:</strong> {{ requirement_salary }}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Open Positions:</strong> {{ positions_count }}</p>
</div>

<p>Due to the priority nature of this recruitment, we recommend reviewing and submitting your profile promptly.</p>

<div style="margin: 20px 0;">
  <a href="{{ requirement_url }}" style="background-color: #2563eb; color: #ffffff; padding: 10px 22px; text-decoration: none; border-radius: 6px; font-weight: 700; display: inline-block;">View Requirement & Express Interest</a>
</div>

<p>Warm regards,<br>
<strong>SevaJobs Fast-Track Recruitment Desk</strong></p>""",
        "body_plain": """Dear {{ candidate_name }},

A new, priority institutional teaching requirement has just been approved on SevaJobs matching your profile in {{ candidate_subject }}:

VIP Urgent Requirement: {{ requirement_subject }} ({{ requirement_grade }})
Institution: {{ institution_name }}
Location: {{ requirement_location }}
Experience Needed: {{ requirement_experience }}
Remuneration: {{ requirement_salary }}
Positions: {{ positions_count }}

Apply / View: {{ requirement_url }}

Warm regards,
SevaJobs Fast-Track Recruitment Desk""",
    },
}


