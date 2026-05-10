from django.db import models
from accounts.models import User

class PlacementDrive(models.Model):
    JOB_TYPE_CHOICES = (
        ('full_time',  'Full Time'),
        ('internship', 'Internship'),
        ('part_time',  'Part Time'),
    )

    BRANCH_CHOICES = (
        ('ALL', 'All Branches'),
        ('CSE', 'Computer Science'),
        ('ECE', 'Electronics & Communication'),
        ('ME',  'Mechanical Engineering'),
        ('CE',  'Civil Engineering'),
        ('EE',  'Electrical Engineering'),
        ('IT',  'Information Technology'),
    )

    STATUS_CHOICES = (
        ('active', 'Active'),
        ('closed', 'Closed'),
    )

    SALARY_TYPE_CHOICES = (
        ('ctc', 'CTC (Cost to Company)'),
        ('lpa', 'LPA (Lakhs Per Annum)'),
        ('stipend', 'Stipend (Per Month)'),
        ('not_disclosed', 'Not Disclosed')
    )

    posted_by       = models.ForeignKey(User, on_delete=models.CASCADE)
    company         = models.CharField(max_length=100)
    company_logo    = models.ImageField(upload_to='company_logos/', blank=True, null=True, help_text="Upload company logo")
    role            = models.CharField(max_length=100)
    description     = models.TextField()
    location        = models.CharField(max_length=100)    
    # Salary Structure
    salary_amount   = models.FloatField(null=True, blank=True, help_text="Enter the numeric value (e.g., 12.5)")
    salary_type     = models.CharField(max_length=20, choices=SALARY_TYPE_CHOICES, default='lpa')    
    job_type        = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    eligible_branch = models.CharField(max_length=10, choices=BRANCH_CHOICES, default='ALL')
    min_cgpa        = models.FloatField(default=0.0)
    skills_required = models.TextField(blank=True)
    deadline        = models.DateField()
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company} - {self.role}"

    # Helper property to easily display the formatted salary in templates
    @property
    def formatted_salary(self):
        # Safety check: if the salary amount is missing (old data), return a default
        if self.salary_amount is None:
            return "N/A"
            
        if self.salary_type == 'not_disclosed':
            return "Not Disclosed"
        elif self.salary_type == 'stipend':
            return f"₹{self.salary_amount:,.0f}/mo"
        elif self.salary_type == 'ctc':
            return f"₹{self.salary_amount:,.1f} CTC"
        else: # lpa
            return f"₹{self.salary_amount:,.1f} LPA"


class Application(models.Model):
    STATUS_CHOICES = (
        ('applied',     'Applied'),
        ('shortlisted', 'Shortlisted'),
        ('rejected',    'Rejected'),
        ('selected',    'Selected'),
    )

    student    = models.ForeignKey(User, on_delete=models.CASCADE)
    drive      = models.ForeignKey(PlacementDrive, on_delete=models.CASCADE)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='applied')
    applied_at = models.DateTimeField(auto_now_add=True)
    resume     = models.FileField(upload_to='application_resumes/', blank=True, null=True)

    class Meta:
        unique_together = ('student', 'drive')

    def __str__(self):
        return f"{self.student.username} → {self.drive.company}"


class Interview(models.Model):
    STATUS_CHOICES = (
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )

    application  = models.OneToOneField(Application, on_delete=models.CASCADE)
    scheduled_at = models.DateTimeField()
    location     = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)
    notes        = models.TextField(blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    created_at   = models.DateTimeField(auto_now_add=True)

class Bookmark(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    drive = models.ForeignKey(PlacementDrive, on_delete=models.CASCADE, related_name='bookmarks')
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'drive') # Prevents a student from saving the same drive twice

class Conversation(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_conversations')
    recruiter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recruiter_conversations')
    drive = models.ForeignKey(PlacementDrive, on_delete=models.CASCADE)
    
    # The Timer: If null, student is locked. If set to a future time, student can type.
    student_chat_unlocked_until = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'recruiter', 'drive')

    def __str__(self):
        return f"Chat: {self.student.username} & {self.recruiter.username} for {self.drive.role}"

class ChatMessage(models.Model):
    SENDER_CHOICES = (
        ('student', 'Student'),
        ('recruiter', 'Recruiter'),
        ('system', 'System'),
    )
    MESSAGE_TYPE_CHOICES = (
        ('text', 'Text'),           # Free text (Recruiter always, Student if unlocked)
        ('template', 'Template'),   # Student predefined button click
        ('file', 'File Upload'),    # Document/Image sharing
        ('system', 'System Alert'), # e.g., "Chat unlocked for 5 mins"
    )

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.CharField(max_length=10, choices=SENDER_CHOICES)
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPE_CHOICES, default='text')
    
    content = models.TextField(blank=True) # Text content or template label
    
    # For file uploads (Resumes, Marksheets, Offer Letters)
    file = models.FileField(upload_to='chat_files/', blank=True, null=True)
    file_category = models.CharField(max_length=50, blank=True) # e.g., 'resume', 'marksheet', 'offer_letter'
    
    # For template actions
    template_action = models.CharField(max_length=50, blank=True) # e.g., 'trouble_joining', 'will_attend'
    
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender}: {self.content[:30]}"