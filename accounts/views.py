import re
import openpyxl
from decimal import Decimal
import calendar
from datetime import date, datetime, time
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Avg
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_protect
from django.utils.timezone import localdate
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
from .models import SalaryGrade
import uuid
import json
import base64
import qrcode
from io import BytesIO
from django.utils.timezone import now
from django.core.exceptions import ValidationError
from .models import LeaveRequest

from .models import (
    Employee,
    AttendanceRecord,
    Message,
    FAQ,
    Announcement,
    EmployeePerformance,
    WeeklyPerformanceSummary,
    WeeklyActivity,
)

# Fixed annual leave allocations for regular employees
ANNUAL_VACATION_LEAVE_DAYS = 15
ANNUAL_SICK_LEAVE_DAYS = 15

LEAVE_LIMITS = {
    "VL": 15,     # Vacation Leave (cumulative)
    "SL": 15,     # Sick Leave (cumulative)
    "SPL": 3,     # Special Privilege (non-cumulative)
    "WL": 5,      # Wellness Leave (non-cumulative)
    "PL": 7,      # Paternity Leave
    "ML": 105,    # Maternity Leave
    "SP": 7,      # Solo Parent Leave
    "EL": 5,      # Emergency Leave
}

def generate_next_emp_id():
    last = Employee.objects.order_by("-emp_id").first()
    if not last or not last.emp_id.startswith("EMP"):
        return "EMP001"
    suffix = last.emp_id[3:]
    try:
        num = int(suffix)
    except ValueError:
        return "EMP001"
    return f"EMP{num + 1:03d}"


def get_current_period(today):
    if today.day <= 15:
        start = today.replace(day=1)
        end = today.replace(day=15)
    else:
        start = today.replace(day=16)
        last_day = calendar.monthrange(today.year, today.month)[1]
        end = today.replace(day=last_day)
    return start, end


def get_half_month_periods(hire_date, today):
    if not hire_date:
        return [get_current_period(today)]
    periods = []
    current = date(hire_date.year, hire_date.month, 1)
    while current <= today:
        mid = current.replace(day=15)
        last_day = calendar.monthrange(current.year, current.month)[1]
        second_start = current.replace(day=16)
        second_end = current.replace(day=last_day)

        if mid >= hire_date and mid <= today:
            periods.append((current, mid))
        if second_end >= hire_date and second_start <= today:
            periods.append((second_start, second_end))

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1)
        else:
            current = current.replace(month=current.month + 1, day=1)
    periods.sort(key=lambda p: (p[0], p[1]))
    return periods


def home(request):
    latest_announcements = Announcement.objects.filter(is_active=True)[:3]
    return render(
        request,
        "accounts/home.html",
        {"announcements": latest_announcements},
    )


def _is_admin(user):
    return user.is_staff


@csrf_protect
def adminlogin(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            return redirect("adminemployee")
        else:
            error = "Invalid credentials or you are not authorized as an admin."
            return render(request, "accounts/adminlogin.html", {"error": error})

    return render(request, "accounts/adminlogin.html")


@login_required
def adminlogout(request):
    logout(request)
    return redirect("adminlogin")


@csrf_protect
def employeelogin(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user is not None and not user.is_staff:
            login(request, user)
            return redirect("employeedash")
        else:
            error = "Invalid credentials or account is not an employee account."
            return render(request, "accounts/employeelogin.html", {"error": error})

    return render(request, "accounts/employeelogin.html")


@login_required
@user_passes_test(_is_admin)
def admindash(request):
    employee_count = Employee.objects.filter(is_archived=False).count()
    pending_messages_count = Message.objects.filter(
        status=Message.Status.PENDING
    ).count()

    today = localdate()
    today_records = AttendanceRecord.objects.filter(date=today)

    present = today_records.filter(status=AttendanceRecord.Status.PRESENT).count()
    late = today_records.filter(status=AttendanceRecord.Status.LATE).count()
    absent = today_records.filter(status=AttendanceRecord.Status.ABSENT).count()
    fieldwork = today_records.filter(status=AttendanceRecord.Status.FIELDWORK).count()
    health = today_records.filter(status=AttendanceRecord.Status.HEALTH).count()

    total = present + late + absent + fieldwork + health
    if total == 0:
        total = 1

    def pct(x):
        return int((x / total) * 100)

    start_of_week = today - timedelta(days=today.weekday())
    weekdays = [start_of_week + timedelta(days=i) for i in range(5)]

    daily_averages = []
    for day in weekdays:
        avg = (
            AttendanceRecord.objects.filter(
                date=day,
                hours_worked__isnull=False,
            ).aggregate(avg=Avg("hours_worked"))["avg"]
            or Decimal("0")
        )
        daily_averages.append(float(avg))

    max_hours = max(daily_averages) or 1
    x_positions = [5, 25, 45, 65, 85]
    svg_points = []

    for x, hours in zip(x_positions, daily_averages):
        y = 45 - (hours / max_hours * 35)
        svg_points.append(f"{x},{round(y, 2)}")

    context = {
        "employee_count": employee_count,
        "pending_messages_count": pending_messages_count,
        "present": present,
        "late_pct": pct(late),
        "late": late,
        "absent": absent,
        "fieldwork": fieldwork,
        "health": health,
        "total_att": total,
        "present_pct": pct(present),
        "absent_pct": pct(absent),
        "fieldwork_pct": pct(fieldwork),
        "health_pct": pct(health),
        "chart_points": " ".join(svg_points),
    }

    return render(request, "accounts/admindash.html", context)


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def adminemployee(request):
    q = request.GET.get("q", "").strip()
    dept = request.GET.get("dept", "").strip()
    status = request.GET.get("status", "").strip()
    edit_id = request.GET.get("edit")
    show_archived = request.GET.get("archived") == "1"

    show_sg_editor = request.GET.get("edit_sg") == "1"
    salary_grades = SalaryGrade.objects.all().order_by("grade")

    # AUTO-CREATE SG rows if none exist (production fix)
    if not salary_grades.exists():
        for i in range(1, 28):  # SG-1 to SG-33
            SalaryGrade.objects.create(
                grade=i,
                monthly_salary=Decimal("0.00")
        )
    salary_grades = SalaryGrade.objects.all().order_by("grade")

    employees = Employee.objects.filter(is_archived=show_archived)
    if q:
        employees = employees.filter(
            Q(emp_id__icontains=q)
            | Q(fname__icontains=q)
            | Q(lname__icontains=q)
            | Q(position__icontains=q)
            | Q(dept__icontains=q)
        )

    if dept:
        employees = employees.filter(dept=dept)

    if status:
        employees = employees.filter(emp_status=status)

    show_form = request.GET.get("add") == "1" or bool(edit_id)
    edit_employee = get_object_or_404(Employee, pk=edit_id) if edit_id else None

    # ✅ LEAVE APPROVAL HANDLER (SAFE)
    leave_id = request.POST.get("leave_id")
    action = request.POST.get("action")

    if leave_id and action:
        try:
            leave = LeaveRequest.objects.get(id=leave_id)

            if action == "approve":
                leave.status = "APPROVED"
                leave.responded_at = timezone.now()

                # ✅ CREATE ATTENDANCE = ON LEAVE
                current = leave.start_date
                while current <= leave.end_date:
                    if current.weekday() < 5:  # weekdays only
                        record, created = AttendanceRecord.objects.get_or_create(
                            employee=leave.employee,
                            date=current,
                        )

                        if record.status in [
                            AttendanceRecord.Status.ABSENT,
                            AttendanceRecord.Status.LATE,
                            AttendanceRecord.Status.PRESENT,
                            None
                        ]:
                            record.status = AttendanceRecord.Status.ON_LEAVE
                            record.save()
                    current += timedelta(days=1)
            elif action == "reject":
                leave.status = "REJECTED"
                leave.responded_at = timezone.now()

            leave.save()
        except LeaveRequest.DoesNotExist:
            pass

        return redirect(request.path + "?leave=1")

    # ================= POST =================
    if request.method == "POST":
        # Excel upload
        if request.POST.get("bulk_upload"):
            excel_file = request.FILES.get("excel_file")

            if not excel_file:
                messages.error(request, "No file uploaded.")
                return redirect(reverse("adminemployee") + "?add=1")

            try:
                wb = openpyxl.load_workbook(excel_file)
                sheet = wb.active
            except Exception:
                messages.error(request, "Invalid Excel file.")
                return redirect(reverse("adminemployee") + "?add=1")

            # ✅ GET HEADERS
            headers = [cell.value for cell in sheet[1]]

            # ✅ EXPECTED FORMAT (STRICT)
            required_columns = [
                "fname", "lname", "email", "birthday",
                "employment_status", "department", "position",
                "salary_grade", "jo_daily_rate"
            ]

            # ❌ REJECT IF NOT MATCH
            if headers != required_columns:
                messages.error(request, "Invalid Excel format. Please use the correct template.")
                return redirect(reverse("adminemployee") + "?add=1")

            # TEMP SUCCESS MESSAGE
            # ✅ PROCESS ROWS
            success_count = 0
            error_count = 0
            duplicate_count = 0

            current_id = generate_next_emp_id()
            VALID_STRUCTURE = {
                "Office of the Municipal Mayor": {
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                    "Senior Administrative Assistant II / Private Secretary II": "SG-18",
                    "Administrative Aide IV (Driver II)": "SG-4",
                    "Security Officer III": "SG-18",
                    "Barangay Health Aide": "SG-4",
                },
                "Office of the Municipal Administrator": {
                    "MGDH I (Municipal Administrator)": "SG-24",
                    "Waterworks Supervisor": "SG-14",
                    "Population Program Worker II": "SG-7",
                },
                "Office of the Municipal Vice Mayor": {
                    "Municipal Vice Mayor": "SG-25",
                },
                "Office of the Municipal HRMO": {
                    "MGDH I (Human Resource Management Officer)": "SG-24",
                },
                "Public Employment Service Office": {
                    "Senior Labor and Employment Officer": "SG-19",
                },
                "Office on Public Affairs & Information Assistance": {
                    "Barangay Health Aide": "SG-4",
                },
                "Business Permit and Licensing Office": {
                    "Senior Administrative Assistant II (Data Controller III)": "SG-15",
                },
                "Sangguniang Bayan Members": {
                    "Sangguniang Bayan Member": "SG-24",
                },
                "Office of the Secretary to the Sangguniang Bayan": {
                    "Secretary to the Sangguniang Bayan": "SG-24",
                    "Local Legislative Staff Officer III": "SG-18",
                    "Local Legislative Staff Officer II": "SG-11",
                    "Local Legislative Staff Assistant I": "SG-8",
                    "Local Legislative Staff Employee II": "SG-4",
                    "Administrative Aide II (Bookbinder II)": "SG-2",
                },
                "Office of the Municipal Budget": {
                    "Municipal Budget Officer": "SG-24",
                    "Administrative Aide IV (Budgeting Aide)": "SG-4",
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                },
                "Office of the Municipal Planning & Development Coordinator": {
                    "MGDH II (Municipal Planning & Development Coordinator)": "SG-24",
                    "Administrative Officer I (Planning Officer I)": "SG-11",
                    "Administrative Aide IV (Clerk II)": "SG-4",
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                },
                "Office of the Municipal Accountant": {
                    "Administrative Officer V (Municipal Accountant)": "SG-18",
                    "Administrative Aide IV (Clerk II)": "SG-4",
                    "Administrative Assistant III (Bookkeeper II)": "SG-9",
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                },
                "Office of the Municipal General Services": {
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                    "Administrative Aide IV (Driver II)": "SG-4",
                    "Water Pump Operator": "SG-4",
                },
                "Local Youth Development Office": {
                    "Youth Development Officer I": "SG-10",
                },
                "Office of the Municipal Treasurer": {
                    "Municipal Treasurer II": "SG-24",
                    "Cemetery Caretaker": "SG-3",
                    "Administrative Aide IV (Clerk II)": "SG-4",
                    "Administrative Officer III (Cashier II)": "SG-14",
                    "Revenue Collection Clerk II": "SG-7",
                    "Revenue Collection Clerk I": "SG-5",
                    "Administrative Aide VI (Cash Clerk III)": "SG-6",
                },
                "Market / Fishport": {
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                },
                "Office of the Municipal Assessor": {
                    "Municipal Assessor II": "SG-24",
                    "Assessment Clerk I": "SG-6",
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                    "Administrative Aide VI (Equipment Operator II)": "SG-8",
                },
                "Office of the Municipal Health Officer": {
                    "Rural Health Physician": "SG-24",
                    "Nurse I": "SG-15",
                    "Midwife II": "SG-11",
                    "Medical Technologist I": "SG-11",
                    "Ambulance Driver": "SG-4",
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                    "Sanitation Inspector I": "SG-9",
                },
                "Nutrition Office": {
                    "Nutrition Officer II": "SG-15",
                    "Barangay Health Aide": "SG-4",
                },
                "Office of the Municipal Civil Registrar": {
                    "Municipal Civil Registrar II": "SG-24",
                    "Administrative Aide IV (Bookbinder II)": "SG-4",
                    "Water Pump Operator": "SG-4",
                },
                "Office of the Municipal Social Welfare and Development Officer": {
                    "Municipal Social Welfare and Development Officer": "SG-24",
                    "Municipal Social Welfare Assistant": "SG-8",
                    "Day Care Worker I": "SG-6",
                },
                "Office of the Municipal Agriculture": {
                    "Municipal Agricultural Officer": "SG-20",
                    "Agricultural Technologist": "SG-10",
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                },
                "Office of the MENRO": {
                    "Administrative Aide IV (Records Officer II)": "SG-10",
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                },
                "Office of the Municipal Disaster Risk Reduction & Management Officer": {
                    "Municipal Disaster Risk Reduction and Management Officer": "SG-24",
                    "Administrative Aide IV (Computer Operator II)": "SG-6",
                    "Local Disaster Risk Reduction & Management Assistant": "SG-8",
                },
                "Office of the Municipal Engineer": {
                    "Administrative Aide I (Utility Worker I)": "SG-1",
                },
            }
            for row in sheet.iter_rows(min_row=2, values_only=True):
                try:
                    # ✅ NORMALIZE FIRST (PUT THIS AT THE VERY TOP)
                    fname = str(row[0]).strip().title()
                    lname = str(row[1]).strip().title()
                    email = str(row[2]).strip().lower()
                    # ✅ STRONG DUPLICATE CHECK (ALL must match)
                    dob_value = row[3]

                    if isinstance(dob_value, datetime):
                        dob_value = dob_value.date()
                    # 2️⃣ VALIDATE
                    if not fname or not lname:
                        error_count += 1
                        continue

                    if Employee.objects.filter(
                        fname=fname,
                        lname=lname,
                        dob=dob_value,
                        email=email
                    ).exists():
                        duplicate_count += 1
                        continue
                    status = str(row[4]).strip().lower()
                    
                    # ✅ REGULAR
                    if status == "regular":
                        emp_status = "Regular"

                        dept_val = str(row[5]).strip()
                        pos_val = str(row[6]).strip().title()

                        # ❌ missing fields
                        if not dept_val or not pos_val:
                            error_count += 1
                            continue

                        # ❌ invalid department
                        if dept_val not in VALID_STRUCTURE:
                            error_count += 1
                            continue

                        # ❌ invalid position
                        if pos_val not in VALID_STRUCTURE[dept_val]:
                            error_count += 1
                            continue

                        # ✅ AUTO-FIX salary grade (IGNORE Excel SG)
                        dept = dept_val
                        position = pos_val
                        salary_grade = VALID_STRUCTURE[dept_val][pos_val]

                        jo_rate = None
                    # ✅ JOB ORDER
                    elif status == "job order":
                        emp_status = "Job Order"
                        if row[8] is None:
                            error_count += 1
                            continue

                        dept = None
                        position = None
                        salary_grade = None
                        
                        try: 
                            jo_rate = Decimal(str(row[8]))
                        except:
                            error_count += 1
                            continue
                    else:
                        error_count += 1
                        continue
                    emp = Employee(
                        emp_id=current_id,
                        fname=fname,
                        lname=lname,
                        email=email,
                        dob=dob_value,
                        emp_status=emp_status,
                        dept=dept,
                        position=position,
                        salary_grade=salary_grade,
                        jo_daily_rate=jo_rate,
                    )

                    emp.full_clean()
                    emp.save()
                    # ✅ increment ID
                    num = int(current_id.replace("EMP", ""))
                    current_id = f"EMP{num + 1:03d}"

                    # ✅ CREATE USER (same as your system)
                    if not User.objects.filter(username=emp.emp_id).exists():
                        user = User.objects.create_user(
                            username=emp.emp_id,
                            password=emp.emp_id,
                            first_name=emp.fname,
                            last_name=emp.lname,
                            email=emp.email,
                        )
                        emp.user = user
                        emp.save()

                    success_count += 1

                except ValidationError:
                    error_count += 1
                    continue

            # ✅ FINAL MESSAGE
            messages.success(
                request,
                f"Uploaded: {success_count} successful, {duplicate_count} duplicates, {error_count} failed."
            )
            return redirect(reverse("adminemployee") + "?add=1")

        # ---- Salary Grade update ----
        if request.POST.get("update_sg"):
            for sg in salary_grades:
                field = f"sg_{sg.grade}"
                if field in request.POST:
                    try:
                        sg.monthly_salary = Decimal(request.POST[field])
                        sg.save()
                    except Exception:
                        pass

            messages.success(request, "Salary grades updated successfully.")
            return redirect("adminemployee")

        # ---- Employee Add / Edit ----
        data = request.POST
        edit_emp_id = data.get("edit_emp_id")

        emp = (
            get_object_or_404(Employee, pk=edit_emp_id)
            if edit_emp_id
            else Employee(emp_id=generate_next_emp_id())
        )

        emp.fname = data.get("fname", "").strip()
        emp.lname = data.get("lname", "").strip()
        emp.email = data.get("email", "").strip()
        emp.phone = data.get("phone", "").strip()
        emp.position = data.get("position", "").strip()
        emp.dept = data.get("department", "").strip()
        emp.salary_grade = data.get("salary_grade", "").strip()
        emp.dob = data.get("birthday") or None
        emp.date_hired = data.get("dateHired") or None
        emp.civil_status = data.get("civil_status") or None
        emp.emp_status = data.get("employment_status")

        emp.address = data.get("street", "")
        emp.brgy = data.get("barangay", "")
        emp.city = data.get("municipality", "")
        emp.province = data.get("province", "")
        emp.zipcode = data.get("zip", "")
        emp.emc_name = data.get("contactName", "")
        emp.emc_relation = data.get("relationship", "")
        emp.emc_phone = data.get("contactPhone", "")

        if emp.emp_status == Employee.EmpStatus.JOB_ORDER:
            try:
                emp.jo_daily_rate = Decimal(data.get("jo_daily_rate"))
            except Exception:
                emp.jo_daily_rate = None
        else:
            emp.jo_daily_rate = None

        try:
            emp.full_clean()  # ✅ triggers validation
            emp.save()
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect("adminemployee")

        if not edit_emp_id and not User.objects.filter(username=emp.emp_id).exists():
            user = User.objects.create_user(
                username=emp.emp_id,
                password=emp.emp_id,
                first_name=emp.fname,
                last_name=emp.lname,
                email=emp.email,
            )
            emp.user = user
            emp.save()  # ✅ keep this as is (DO NOT change)

            return redirect("adminemployee")
    # ================= GET =================
    today = localdate()
    rec_map = {
    r.employee.emp_id: r
    for r in AttendanceRecord.objects.filter(date=today)
    }


    for e in employees:
        e.today_att = rec_map.get(e.emp_id)

    leave_requests = LeaveRequest.objects.select_related("employee").order_by("-date_filed")

    status_filter = request.GET.get("status")

    if status_filter:
        leave_requests = leave_requests.filter(status=status_filter)
    else:
        pending = leave_requests.filter(status="PENDING")

        recent = leave_requests.filter(
            status__in=["APPROVED", "REJECTED"],
            responded_at__gte=timezone.now() - timedelta(days=2)
        )

        leave_requests = (pending | recent).distinct()

    context = {
        "employees": employees,
        "q": q,
        "dept": dept,
        "status": status,
        "dept_choices": Employee.objects.values_list("dept", flat=True).distinct(),
        "status_choices": Employee.EmpStatus.choices,
        "show_form": show_form,
        "edit_employee": edit_employee,
        "next_emp_id": generate_next_emp_id(),
        "is_archives": show_archived,
        "show_sg_editor": show_sg_editor,
        "salary_grades": salary_grades,
        "show_leave": request.GET.get("leave") == "1",
        "leave_requests": leave_requests,

    }


    return render(request, "accounts/adminemployee.html", context)


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def employee_archive(request, emp_id):
    # move employee to archives (soft delete)
    employee = get_object_or_404(Employee, pk=emp_id)
    if request.method == "POST":
        employee.is_archived = True
        employee.save()
    return redirect("adminemployee")


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def employee_recover(request, emp_id):
    # recover employee back to active list
    employee = get_object_or_404(Employee, pk=emp_id)
    if request.method == "POST":
        employee.is_archived = False
        employee.save()
    return redirect("adminemployee")


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def employee_delete(request, emp_id):
    employee = get_object_or_404(Employee, pk=emp_id)

    if request.method == "POST":
        try:
            if employee.user_id:
                user = User.objects.filter(pk=employee.user_id).first()
                if user:
                    user.delete()
            employee.delete()
        except Exception:
            pass

    return redirect(reverse("adminemployee") + "?archived=1")

@login_required
@user_passes_test(_is_admin)
@csrf_protect
def employee_reset_password(request, emp_id):
    employee = get_object_or_404(Employee, pk=emp_id)

    if request.method == "POST":
        if employee.user:
            user = employee.user
            user.set_password(employee.emp_id)
            user.save()
            messages.success(
                request,
                f"Password reset to default ({employee.emp_id}).",
            )
        else:
            messages.error(
                request,
                "This employee does not have a linked user account.",
            )

    return redirect("adminemployee")


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def employee_toggle_attendance(request, emp_id):
    """
    Admin Time-in / Time-out for an employee.
    Uses Asia/Manila local time; one record per day; 8:00–17:00 schedule.
    """
    if request.method != "POST":
        return redirect("adminemployee")

    employee = get_object_or_404(Employee, pk=emp_id)

    # Now in Philippine Standard Time if TIME_ZONE="Asia/Manila"
    now = timezone.localtime()
    today = now.date()

    # Fixed schedule: 8:00 AM to 5:00 PM PST, Monday–Saturday
    scheduled_start = time(8, 0)
    scheduled_end = time(17, 0)

    # Get or create today's attendance record
    record, created = AttendanceRecord.objects.get_or_create(
        employee=employee,
        date=today,
        defaults={"status": AttendanceRecord.Status.PRESENT},
    )

    # No time_in yet → Time-in
    if record.time_in is None:
        record.time_in = now.time()

        # Lateness based on 8:00 AM PST
        if record.time_in <= scheduled_start:
            record.status = AttendanceRecord.Status.PRESENT
        else:
            record.status = AttendanceRecord.Status.LATE

    # Already time_in but no time_out → Time-out
    elif record.time_out is None:
        record.time_out = now.time()

        in_dt = timezone.make_aware(
                    datetime.combine(today, record.time_in)
                )
        diff = now - in_dt

        out_dt = datetime.combine(today, record.time_out)
        start_dt = datetime.combine(today, scheduled_start)
        end_dt = datetime.combine(today, scheduled_end)

        # Clamp to 8:00–17:00
        if in_dt < start_dt:
            in_dt = start_dt
        if out_dt > end_dt:
            out_dt = end_dt

        delta = out_dt - in_dt
        seconds = max(delta.total_seconds(), 0)
        hours = Decimal(seconds) / Decimal("3600")
        record.hours_worked = hours.quantize(Decimal("0.01"))

    # If both exist, do nothing (already completed)
    record.save()

    return redirect("adminemployee")


@login_required
@user_passes_test(_is_admin)
def time_tracking(request):
    today = localdate()

    selected_date = request.GET.get("date")
    selected_department = request.GET.get("department")

    records = AttendanceRecord.objects.select_related("employee")

    # Filter by date
    if selected_date:
        records = records.filter(date=selected_date)
    else:
        records = records.filter(date=today)

    # Filter by department (FIXED: dept instead of department)
    if selected_department:
        records = records.filter(employee__dept=selected_department)

    present = records.filter(status=AttendanceRecord.Status.PRESENT).count()
    late = records.filter(status=AttendanceRecord.Status.LATE).count()
    on_leave = records.filter(
        status__in=[
            AttendanceRecord.Status.FIELDWORK,
            AttendanceRecord.Status.HEALTH,
            AttendanceRecord.Status.ON_LEAVE,
        ]
    ).count()

    avg_hours = records.aggregate(avg=Avg("hours_worked"))["avg"] or 0

    # Get unique departments (FIXED: dept instead of department)
    departments = (
        Employee.objects
        .exclude(dept__isnull=True)
        .exclude(dept__exact="")
        .values_list("dept", flat=True)
        .distinct()
        .order_by("dept")
    )

    context = {
        "today_present": present,
        "today_on_leave": on_leave,
        "today_late": late,
        "today_avg_hours": round(float(avg_hours), 2) if avg_hours else 0,
        "recent_logs": records,
        "departments": departments,
        "selected_department": selected_department,
    }

    return render(request, "accounts/time.html", context)


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def message_admin(request):
    if request.method == "POST":
        form_type = request.POST.get("form_type")

        if form_type == "faq":
            q = request.POST.get("faqQuestion", "").strip()
            a = request.POST.get("faqAnswer", "").strip()
            c = request.POST.get("faqCategory") or FAQ.Category.GENERAL
            if q and a:
                FAQ.objects.create(question=q, answer=a, category=c)
            return redirect("message")

        if form_type == "announcement":
            title = request.POST.get("annTitle", "").strip()
            date_val = request.POST.get("annDate") or None
            body = request.POST.get("annBody", "").strip()
            if title and body:
                Announcement.objects.create(title=title, body=body, date=date_val)
            return redirect("message")

    messages_qs = Message.objects.all()
    faqs = FAQ.objects.filter(is_active=True)
    announcements = Announcement.objects.filter(is_active=True)

    context = {
        "messages": messages_qs,
        "faqs": faqs,
        "announcements": announcements,
    }
    return render(request, "accounts/message.html", context)


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def message_update_status(request, pk):
    msg = get_object_or_404(Message, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "respond":
            msg.status = Message.Status.RESPONDED
        elif action == "read":
            msg.status = Message.Status.READ
        msg.save()
    return redirect("message")


def _get_employee_from_user(user):
    if not user.is_authenticated:
        return None
    return getattr(user, "employee_profile", None)


@login_required(login_url="employeelogin")
def employeedash(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return redirect("employeelogin")
    
    leave_balances = []

    for code, limit in LEAVE_LIMITS.items():
        approved = LeaveRequest.objects.filter(
            employee=employee,
            leave_type=code,
            status="APPROVED"
        )

        used_days = 0

        for leave in approved:
            current = leave.start_date
            while current <= leave.end_date:
                if current.weekday() < 5:
                    used_days += 1
                current += timedelta(days=1)

        remaining = max(limit - used_days, 0)

        leave_balances.append({
            "name": dict(LeaveRequest.LeaveType.choices).get(code, code),
            "remaining": remaining,
            "limit": limit
        })

    auto_timeout_absentees()

    # Latest announcements for the dashboard
    anns = Announcement.objects.filter(is_active=True)[:5]

    # Today in PST
    today = localdate()
    active_leave = LeaveRequest.objects.filter(
        employee=employee,
        status="APPROVED",
        start_date__lte=today,
        end_date__gte=today
    ).exists()
    today_rec = AttendanceRecord.objects.filter(
        employee=employee,
        date=today
    ).first()

    year_start = max(
        employee.date_hired,
        date(today.year, 1, 1)
    ) if employee.date_hired else date(today.year, 1, 1)

    start_date = year_start  # ✅ ADD THIS

    all_workdays = []
    current = start_date
    while current <= today:
        if current.weekday() < 5:
            all_workdays.append(current)
        current += timedelta(days=1)

    attendance_qs = AttendanceRecord.objects.filter(
        employee=employee,
        date__range=(start_date, today)
    )

    attendance_map = {att.date: att for att in attendance_qs}

    total_lates = 0
    total_absents = 0

    for day in all_workdays:
        att = attendance_map.get(day)

        if att:
            if att.status == AttendanceRecord.Status.LATE:
                total_lates += 1
            elif att.status == AttendanceRecord.Status.ABSENT:
                total_absents += 1
        else:
            total_absents += 1  # ✅ MISSING = ABSENT
            
    late_absent_occurrences = total_lates + total_absents

    # Only REGULAR employees get 15 days sick leave
    is_regular = employee.emp_status == Employee.EmpStatus.REGULAR
    if is_regular:
        sick_annual = 15

        start_date = max(
            employee.date_hired,
            date(today.year, 1, 1)
        ) if employee.date_hired else date(today.year, 1, 1)

        all_workdays = []
        current = start_date

        while current <= today:
            if current.weekday() < 5:
                all_workdays.append(current)
            current += timedelta(days=1)

        attendance_qs = AttendanceRecord.objects.filter(
            employee=employee,
            date__range=(start_date, today)
        )

        attendance_map = {att.date: att for att in attendance_qs}

        total_lates = 0
        total_absents = 0

        for day in all_workdays:
            att = attendance_map.get(day)

            if att:
                if att.status == AttendanceRecord.Status.LATE:
                    total_lates += 1
                elif att.status == AttendanceRecord.Status.ABSENT:
                    total_absents += 1
            else:
                total_absents += 1  # ✅ MISSING = ABSENT

        sick_days_deducted = (
            Decimal(total_absents) * 1 +
            Decimal(total_lates) * Decimal("0.25")
        )

        if sick_days_deducted > sick_annual:
            sick_days_deducted = Decimal(sick_annual)

        sick_remaining = Decimal(sick_annual) - sick_days_deducted

    else:
        sick_annual = 0
        sick_days_deducted = 0
        sick_remaining = 0

    # Pending tasks / upcoming events & deadlines
    pending_activities = WeeklyActivity.objects.filter(
        summary__employee=employee,
        is_done=False,
    ).select_related("summary").order_by(
        "summary__week_end", "id"
    )

    
    context = {
        "employee": employee,
        "announcements": anns,
        "today_attendance": today_rec,

        "active_leave": active_leave,

        "total_lates": total_lates,
        "total_absents": total_absents,
        "late_absent_occurrences": late_absent_occurrences,

        "is_regular": is_regular,
        "sick_annual": sick_annual,
        "sick_days_deducted": sick_days_deducted,
        "sick_remaining": sick_remaining,

        "pending_activities": pending_activities,

        "leave_balances": leave_balances,
    }
    return render(request, "accounts/employeedash.html", context)

@login_required(login_url="employeelogin")
def payslip(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return redirect("employeedash")

    today = localdate()
    hire_date = employee.date_hired or today

    # ===== PERIODS =====
    periods = []
    current = date(hire_date.year, hire_date.month, 1)

    while current <= today:
        last_day = calendar.monthrange(current.year, current.month)[1]
        periods.append((current, current.replace(day=last_day)))

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1)
        else:
            current = current.replace(month=current.month + 1, day=1)

    selected_value = request.GET.get("period")
    if selected_value:
        try:
            s_str, e_str = selected_value.split("_")
            selected_start = date.fromisoformat(s_str)
            selected_end = date.fromisoformat(e_str)
        except:
            selected_start, selected_end = periods[-1]
    else:
        selected_start, selected_end = periods[-1]

    # ✅ ONLY LAST 6 MONTHS (CLEAN DROPDOWN)
    recent_periods = periods[-6:]

    period_options = [
        (
            f"{start.strftime('%Y-%m-%d')}_{end.strftime('%Y-%m-%d')}",
            f"{start.strftime('%b %Y')}"
        )
        for start, end in periods[-6:]
    ]

    selected_period_value = f"{selected_start.strftime('%Y-%m-%d')}_{selected_end.strftime('%Y-%m-%d')}"
    selected_label = selected_start.strftime('%b %Y')

    # ===== DEFAULTS =====
    is_job_order = employee.emp_status == Employee.EmpStatus.JOB_ORDER
    monthly = Decimal("0.00")
    daily_rate = Decimal("0.00")
    absence_deduction = Decimal("0.00")
    absent_days = 0
    deductible_absents = 0
    basic_salary = Decimal("0.00")
    rata = Decimal("0.00")

    # ================= JOB ORDER =================
    if is_job_order:
        daily_rate = employee.jo_daily_rate or Decimal("0")

        payable_days = AttendanceRecord.objects.filter(
            employee=employee,
            date__range=(selected_start, selected_end),
            status__in=[
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.LATE,
                AttendanceRecord.Status.FIELDWORK,
                AttendanceRecord.Status.HEALTH,
            ],
        ).values("date").distinct().count()

        basic_salary = (daily_rate * Decimal(payable_days)).quantize(Decimal("0.01"))

    # ================= REGULAR =================
    else:
        match = re.search(r"\d+", employee.salary_grade or "")
        sg_num = int(match.group()) if match else None

        salary_obj = SalaryGrade.objects.filter(grade=sg_num).first()
        monthly = salary_obj.monthly_salary if salary_obj else Decimal("0")

        daily_rate = (monthly / Decimal("21.75")).quantize(Decimal("0.01"))

        # ✅ GET ATTENDANCE FIRST (FIXED ORDER)
        attendance_qs = AttendanceRecord.objects.filter(
            employee=employee,
            date__range=(selected_start, selected_end)
        )
        attendance_map = {att.date: att for att in attendance_qs}

        # ✅ CORRECT ABSENCE COUNT (FINAL)
        end_date = min(selected_end, today)

        total_absents = 0
        current = selected_start

        while current <= end_date:
            if current.weekday() < 5 and current >= hire_date:
                att = attendance_map.get(current)

                if not att or att.status == AttendanceRecord.Status.ABSENT:
                    total_absents += 1

            current += timedelta(days=1)

        absent_days = total_absents
        basic_salary = monthly

        # ===== YEARLY LEAVE =====
        year_start = max(
            employee.date_hired,
            date(today.year, 1, 1)
        ) if employee.date_hired else date(today.year, 1, 1)

        year_attendance = AttendanceRecord.objects.filter(
            employee=employee,
            date__range=(year_start, today)
        )

        year_lates = 0
        year_absents = 0

        current = year_start
        while current <= today:
            if current.weekday() < 5 and current >= hire_date:
                att = year_attendance.filter(date=current).first()

                if att:
                    if att.status == AttendanceRecord.Status.LATE:
                        year_lates += 1
                    elif att.status == AttendanceRecord.Status.ABSENT:
                        year_absents += 1
                else:
                    year_absents += 1

            current += timedelta(days=1)

        leave_used = (
            Decimal(year_absents) +
            Decimal(year_lates) * Decimal("0.25")
        )

        remaining_sick_leave = max(Decimal("15") - leave_used, 0)

        # ===== MONTH CALC =====
        period_lates = sum(
            1 for att in attendance_map.values()
            if att.status == AttendanceRecord.Status.LATE
        )

        period_leave_used = (
            Decimal(absent_days) +
            Decimal(period_lates) * Decimal("0.25")
        )

        if remaining_sick_leave > 0:
            deductible_absents = max(
                period_leave_used - remaining_sick_leave,
                0
            )
        else:
            deductible_absents = period_leave_used

        # ✅ HARD CAP (CANNOT EXCEED SALARY)
        absence_deduction = min(
            daily_rate * deductible_absents,
            monthly
        ).quantize(Decimal("0.01"))

        rata = Decimal("1000.00")

    # ===== FINAL =====
    philhealth = (monthly * Decimal("0.025")).quantize(Decimal("0.01"))
    total_earnings = basic_salary + rata
    total_deductions = philhealth + absence_deduction
    net_pay = total_earnings - total_deductions

    context = {
        "employee": employee,

        # ✅ ADD THESE BACK (DROPDOWN FIX)
        "period_options": period_options,
        "selected_period_value": selected_period_value,
        "selected_period_label": selected_label,

        "basic_salary": basic_salary,
        "rata": rata,
        "total_earnings": total_earnings,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
        "daily_rate": daily_rate,
        "absent_days": absent_days,
        "deductible_absents": deductible_absents,
        "philhealth": philhealth,
        "absence_deduction": absence_deduction,
    }

    return render(request, "accounts/payslip.html", context)

@login_required(login_url="employeelogin")
def benefits(request):
    employee = _get_employee_from_user(request.user)
    return render(request, "accounts/benefits.html", {"employee": employee})


@login_required(login_url="employeelogin")
def performance(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return redirect("employeedash")

    okrs = EmployeePerformance.objects.filter(
        employee=employee,
        is_active=True,
    ).order_by("-created_at")[:10]

    weekly_summary = (
        WeeklyPerformanceSummary.objects.filter(
            employee=employee,
        )
        .order_by("-week_start")
        .first()
    )

    weekly_activities = weekly_summary.activities.all() if weekly_summary else []

    context = {
        "employee": employee,
        "okrs": okrs,
        "weekly_summary": weekly_summary,
        "weekly_activities": weekly_activities,
    }
    return render(request, "accounts/performance.html", context)


@login_required(login_url="employeelogin")
def announcements(request):
    employee = _get_employee_from_user(request.user)
    anns = Announcement.objects.filter(is_active=True)
    return render(
        request,
        "accounts/announcements.html",
        {"employee": employee, "announcements": anns},
    )


@login_required(login_url="employeelogin")
def help(request):
    employee = _get_employee_from_user(request.user)
    faqs = FAQ.objects.filter(is_active=True)

    faqs_leave = faqs.filter(category=FAQ.Category.LEAVE)
    faqs_payroll = faqs.filter(category=FAQ.Category.PAYROLL)
    faqs_benefits = faqs.filter(category=FAQ.Category.BENEFITS)

    context = {
        "employee": employee,
        "faqs_leave": faqs_leave,
        "faqs_payroll": faqs_payroll,
        "faqs_benefits": faqs_benefits,
    }
    return render(request, "accounts/help.html", context)


@login_required(login_url="employeelogin")
@csrf_protect
def employee_profile(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return redirect("employeedash")

    info_success = False
    pwd_success = False
    pwd_error = None

    if request.method == "POST":
        form_type = request.POST.get("form_type")

        if form_type == "info":
            employee.phone = request.POST.get("phone", "")
            employee.address = request.POST.get("address", "")
            employee.brgy = request.POST.get("brgy", "")
            employee.city = request.POST.get("city", "")
            employee.province = request.POST.get("province", "")
            employee.zipcode = request.POST.get("zipcode", "")
            employee.emc_name = request.POST.get("emc_name", "")
            employee.emc_relation = request.POST.get("emc_relation", "")
            employee.emc_phone = request.POST.get("emc_phone", "")
            employee.save()
            info_success = True

        elif form_type == "password":
            old_pwd = request.POST.get("old_password") or ""
            new_pwd1 = request.POST.get("new_password1") or ""
            new_pwd2 = request.POST.get("new_password2") or ""

            if not request.user.check_password(old_pwd):
                pwd_error = "Old password is incorrect."
            elif not new_pwd1 or new_pwd1 != new_pwd2:
                pwd_error = "New passwords do not match."
            else:
                request.user.set_password(new_pwd1)
                request.user.save()
                user = authenticate(
                    request,
                    username=request.user.username,
                    password=new_pwd1,
                )
                if user is not None:
                    login(request, user)
                pwd_success = True

    context = {
        "employee": employee,
        "info_success": info_success,
        "pwd_success": pwd_success,
        "pwd_error": pwd_error,
    }
    return render(request, "accounts/employee_profile.html", context)

from django.shortcuts import render, redirect


@login_required(login_url="employeelogin")
def employee_leave(request):
    employee = _get_employee_from_user(request.user)

    if request.method == "POST":
        today = date.today()

        active_leave = LeaveRequest.objects.filter(
            employee=employee,
            status=LeaveRequest.Status.APPROVED,
            start_date__lte=today,
            end_date__gte=today
        ).exists()

        if active_leave:
            return render(request, "accounts/employee_leave.html", {
                "leaves": LeaveRequest.objects.filter(employee=employee).order_by("-date_filed"),
                "today": today,
                "error": "You already have an active leave."
            })
        leave_type = request.POST.get("leave_type")
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        reason = request.POST.get("reason")
        attachment = request.FILES.get("attachment")


        if not start_date or not end_date:
            return redirect("employee_leave")
        
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        # ✅ count weekdays only
        requested_days = 0
        current = start

        while current <= end:
            if current.weekday() < 5:
                requested_days += 1
            current += timedelta(days=1)

        approved_leaves = LeaveRequest.objects.filter(
            employee=employee,
            leave_type=leave_type,
            status="APPROVED"
        )

        used_days = 0

        for leave in approved_leaves:
            current = leave.start_date
            while current <= leave.end_date:
                if current.weekday() < 5:
                    used_days += 1
                current += timedelta(days=1)

        limit = LEAVE_LIMITS.get(leave_type, 0)
        remaining = max(limit - used_days, 0)

        if requested_days > remaining:
            return render(request, "accounts/employee_leave.html", {
                "leaves": LeaveRequest.objects.filter(employee=employee).order_by("-date_filed"),
                "today": date.today(),
                "error": f"You only have {remaining} day(s) left for this leave type."
            })
        
        LeaveRequest.objects.create(
            employee=employee,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            attachment=attachment
        )

        return redirect("employee_leave")
    
    leaves = LeaveRequest.objects.filter(employee=employee).order_by("-date_filed")
    today = date.today()

    active_leave = LeaveRequest.objects.filter(
        employee=employee,
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=today,
        end_date__gte=today
    ).exists()
    status_filter = request.GET.get("status")

    if status_filter:
        leaves = leaves.filter(status=status_filter)

    return render(request, "accounts/employee_leave.html", {
        "leaves": leaves,
        "today": date.today(),
        "active_leave": active_leave,
    })

@login_required
@user_passes_test(_is_admin)
def employee_list(request):
    employees = Employee.objects.filter(is_archived=False).order_by("lname", "fname")

    context = {
        "employees": employees,
    }
    return render(request, "accounts/employeelist.html", context)


@login_required(login_url="employeelogin")
def employee_qr_page(request):
    return render(request, "accounts/employee_qr_scan.html")

from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone
from datetime import date, time
from .models import QRSession


@require_POST
@login_required(login_url="employeelogin")
def employee_qr_submit(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return JsonResponse({"error": "Employee not found"}, status=404)

    # ✅ STEP 1: Validate QR Token
    try:
        data = json.loads(request.body)

        token = data.get("token")
        lat = data.get("lat")
        lng = data.get("lng")
        accuracy = data.get("accuracy")

    except Exception:
        return JsonResponse({"error": "Invalid QR data"}, status=400)

    from .models import QRSession

    qr_session = QRSession.objects.filter(
        token=token,
        is_active=True,
        expires_at__gt=timezone.now(),
    ).first()

    if not qr_session:
        return JsonResponse(
            {"error": "QR code expired or invalid."},
            status=400
        )
    # ✅ LOCATION VALIDATION
    from math import radians, sin, cos, sqrt, atan2

    PAOMBONG_LAT = 14.866707
    PAOMBONG_LNG = 120.807094
    ALLOWED_RADIUS = 5000  # meters

    def distance_meters(lat1, lon1, lat2, lon2):
        R = 6371000
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return R * (2 * atan2(sqrt(a), sqrt(1 - a)))

# If GPS data exists, validate location
    if lat is not None and lng is not None:
        distance = distance_meters(float(lat), float(lng), PAOMBONG_LAT, PAOMBONG_LNG)

        if distance > ALLOWED_RADIUS:
            return JsonResponse(
            {"error": "You are outside the allowed area."},
            status=403
        )

    # Optional: deactivate after use
    qr_session.is_active = False
    qr_session.save()

    # ✅ STEP 2: Continue attendance logic
    now_dt = timezone.localtime()
    today = now_dt.date()
    now_time = now_dt.time()

    attendance, _ = AttendanceRecord.objects.get_or_create(
        employee=employee,
        date=today,
    )

    # TIME IN
    if attendance.time_in is None:
        attendance.time_in = now_time
        attendance.status = (
            AttendanceRecord.Status.LATE
            if now_time > time(8, 15)
            else AttendanceRecord.Status.PRESENT
        )
        attendance.save()

        return JsonResponse({
            "success": True,
            "action": "time_in",
            "message": "Time-in recorded",
        })

    # TIME OUT
    if attendance.time_out is None:
        from datetime import datetime

        in_dt = datetime.combine(today, attendance.time_in)
        diff = now_dt - timezone.make_aware(in_dt)

        if diff.total_seconds() < 300:
            return JsonResponse({
                "error": "Please wait 5 minutes before checking out."
            }, status=400)

        attendance.time_out = now_time
        attendance.hours_worked = round(
            diff.total_seconds() / 3600, 2
        )
        attendance.save()

        return JsonResponse({
            "success": True,
            "action": "time_out",
            "message": "Time-out recorded",
        })

    return JsonResponse({
        "error": "Attendance already completed for today."
    }, status=400)

from django.utils.timezone import localtime
from datetime import datetime, time

def auto_timeout_absentees():
    now = localtime()
    today = now.date()

    if now.time() < time(17, 0):
        return

    records = AttendanceRecord.objects.filter(
        date=today,
        time_in__isnull=False,
        time_out__isnull=True,
    )

    for att in records:
        if not att.time_in:
            continue

        in_dt = timezone.make_aware(
        datetime.combine(today, att.time_in)
        )

        out_dt = timezone.make_aware(
            datetime.combine(today, time(17, 0))
        )

        delta = out_dt - in_dt

        att.time_out = time(17, 0)
        att.hours_worked = round(
            delta.total_seconds() / 3600, 2
        )
        att.save()


def admin_qr_attendance(request):
    from django.utils import timezone
    from .models import QRSession

    # Deactivate old QR sessions
    QRSession.objects.filter(is_active=True).update(is_active=False)

    # Create new QR session
    qr_session = QRSession.objects.create(
        expires_at=timezone.now() + timedelta(minutes=5),
        is_active=True,
    )

    payload = {
        "token": str(qr_session.token),
    }

    qr = qrcode.make(json.dumps(payload))

    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_image = base64.b64encode(buffer.getvalue()).decode()

    context = {
        "qr_image": qr_image,
        "expires_at": qr_session.expires_at,
        "radius": 100
    }

    return render(request, "accounts/admin_qr_attendance.html", context)