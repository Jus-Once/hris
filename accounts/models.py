from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings


class Employee(models.Model):
    class CivilStatus(models.TextChoices):
        SINGLE = "Single", "Single"
        MARRIED = "Married", "Married"
        SEPARATED = "Separated", "Separated"
        WIDOWED = "Widowed", "Widowed"

    class EmpStatus(models.TextChoices):
        REGULAR = "Regular", "Regular"
        JOB_ORDER = "Job Order", "Job Order"

    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
    )

    emp_id = models.CharField(
        max_length=20,
        primary_key=True,
        verbose_name="Employee ID",
    )
    fname = models.CharField(max_length=50, verbose_name="First Name")
    lname = models.CharField(max_length=50, verbose_name="Last Name")
    email = models.EmailField(max_length=100, verbose_name="Email Address")
    phone = models.CharField(max_length=20, verbose_name="Phone Number", blank=True)

    position = models.CharField(max_length=80)
    dept = models.CharField(max_length=80, verbose_name="Department")
    salary_grade = models.CharField(max_length=20, verbose_name="Salary Grade", blank=True)

    dob = models.DateField(verbose_name="Date of Birth", null=True, blank=True)
    date_hired = models.DateField(null=True, blank=True)

    civil_status = models.CharField(
        max_length=20,
        choices=CivilStatus.choices,
        null=True,
        blank=True,
    )

    emp_status = models.CharField(
        max_length=20,
        choices=EmpStatus.choices,
        verbose_name="Employment Status",
    )

    address = models.CharField(
        max_length=150,
        verbose_name="Street Address",
        blank=True,
        help_text="House/Lot no., Street Name",
    )
    brgy = models.CharField(max_length=80, verbose_name="Barangay", blank=True)
    city = models.CharField(max_length=80, verbose_name="Municipality/City", blank=True)
    province = models.CharField(max_length=80, blank=True)
    zipcode = models.CharField(max_length=10, blank=True)

    emc_name = models.CharField(
        max_length=100,
        verbose_name="Emergency Contact Name",
        blank=True,
    )
    emc_relation = models.CharField(
        max_length=50,
        verbose_name="Relationship",
        blank=True,
    )
    emc_phone = models.CharField(
        max_length=20,
        verbose_name="Emergency Contact Phone",
        blank=True,
    )

    def __str__(self):
        return f"{self.emp_id} - {self.fname} {self.lname}"

    @property
    def full_name(self):
        return f"{self.fname} {self.lname}".strip()

    class Meta:
        db_table = "employee"
        ordering = ["lname", "fname"]


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"
        FIELDWORK = "fieldwork", "Fieldwork"
        HEALTH = "health", "Health-related"

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    date = models.DateField()
    time_in = models.TimeField(null=True, blank=True)
    time_out = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PRESENT,
    )
    hours_worked = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total hours worked (e.g. 7.50)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee.emp_id} {self.date} ({self.status})"

    class Meta:
        db_table = "attendance_record"
        ordering = ["-date", "-created_at"]


class Message(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RESPONDED = "responded", "Responded"
        READ = "read", "Read"

    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    message_type = models.CharField(max_length=50, blank=True)
    text = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.message_type or 'Message'}"

    class Meta:
        db_table = "message"
        ordering = ["-created_at"]


class FAQ(models.Model):
    class Category(models.TextChoices):
        LEAVE = "Leave Policies", "Leave Policies"
        PAYROLL = "Payroll", "Payroll"
        BENEFITS = "Benefits", "Benefits"
        GENERAL = "General", "General"

    question = models.CharField(max_length=255)
    answer = models.TextField()
    category = models.CharField(
        max_length=50,
        choices=Category.choices,
        default=Category.GENERAL,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question

    class Meta:
        db_table = "faq"
        ordering = ["-created_at"]


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    class Meta:
        db_table = "announcement"
        ordering = ["-date", "-created_at"]


class EmployeePerformance(models.Model):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="performance_records",
    )
    period_label = models.CharField(max_length=100, blank=True)
    objective_name = models.CharField(max_length=200)
    key_result_name = models.CharField(max_length=200)
    progress_percent = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        base = f"{self.employee.emp_id} - {self.objective_name}"
        if self.period_label:
            return f"{base} ({self.period_label})"
        return base

    class Meta:
        db_table = "employee_performance"
        ordering = ["-created_at"]


class WeeklyPerformanceSummary(models.Model):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="weekly_summaries",
    )
    week_start = models.DateField()
    week_end = models.DateField()
    progress_percent = models.PositiveIntegerField(default=0)
    activities_done = models.PositiveIntegerField(default=0)
    total_activities = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee.emp_id} - {self.week_start} to {self.week_end}"

    class Meta:
        db_table = "weekly_performance_summary"
        ordering = ["-week_start", "-created_at"]


class WeeklyActivity(models.Model):
    summary = models.ForeignKey(
        WeeklyPerformanceSummary,
        on_delete=models.CASCADE,
        related_name="activities",
    )
    description = models.CharField(max_length=255)
    is_done = models.BooleanField(default=False)

    def __str__(self):
        state = "Done" if self.is_done else "Pending"
        return f"{self.summary.employee.emp_id} - {self.description} ({state})"

    class Meta:
        db_table = "weekly_activity"
        ordering = ["id"]