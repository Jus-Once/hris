import re
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
            return redirect("admindash")
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

    employees = Employee.objects.filter(is_archived=show_archived)
    show_qr = request.GET.get("show_qr") == "1"

    qr_image = None

    if show_qr:
        PAOMBONG_LAT = 14.841699
        PAOMBONG_LNG = 120.786550
        ALLOWED_RADIUS_METERS = 300

        payload = {
            "token": str(uuid.uuid4()),
            "expires_at": (now() + timedelta(minutes=5)).isoformat(),
            "lat": PAOMBONG_LAT,
            "lng": PAOMBONG_LNG,
            "radius": ALLOWED_RADIUS_METERS,
        }

        qr = qrcode.make(json.dumps(payload))
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        qr_image = base64.b64encode(buffer.getvalue()).decode()


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

    # ================= POST =================
    if request.method == "POST":

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

        emp.save()

        if not edit_emp_id and not User.objects.filter(username=emp.emp_id).exists():
            user = User.objects.create_user(
                username=emp.emp_id,
                password=emp.emp_id,
                first_name=emp.fname,
                last_name=emp.lname,
                email=emp.email,
            )
            emp.user = user
            emp.save()

        return redirect("adminemployee")

    # ================= GET =================
    today = localdate()
    rec_map = {
        r.employee_id: r
        for r in AttendanceRecord.objects.filter(date=today)
    }

    for e in employees:
        e.today_att = rec_map.get(e.emp_id)

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

        # ✅ QR
        "show_qr": show_qr,
        "qr_image": qr_image,
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
    # permanent delete (from archives)
    employee = get_object_or_404(Employee, pk=emp_id)
    if request.method == "POST":
        if employee.user:
            employee.user.delete()
        employee.delete()
    return redirect("adminemployee")


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

        in_dt = datetime.combine(today, record.time_in)
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
    today_records = AttendanceRecord.objects.filter(date=today)

    present = today_records.filter(status=AttendanceRecord.Status.PRESENT).count()
    late = today_records.filter(status=AttendanceRecord.Status.LATE).count()
    on_leave = today_records.filter(
        status__in=[AttendanceRecord.Status.FIELDWORK, AttendanceRecord.Status.HEALTH]
    ).count()

    avg_hours = today_records.aggregate(avg=Avg("hours_worked"))["avg"] or 0

    recent_logs = AttendanceRecord.objects.select_related("employee")[:10]

    context = {
        "today_present": present,
        "today_on_leave": on_leave,
        "today_late": late,
        "today_avg_hours": round(float(avg_hours), 2) if avg_hours else 0,
        "recent_logs": recent_logs,
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

    # Latest announcements for the dashboard
    anns = Announcement.objects.filter(is_active=True)[:5]

    # Today in PST
    today = localdate()
    today_rec = AttendanceRecord.objects.filter(
        employee=employee,
        date=today
    ).first()

    # Leave / lates / absences overview (current year)
    start_of_year = date(today.year, 1, 1)
    year_att_qs = AttendanceRecord.objects.filter(
        employee=employee,
        date__gte=start_of_year,
    )

    total_lates = year_att_qs.filter(
        status=AttendanceRecord.Status.LATE
    ).count()

    total_absents = year_att_qs.filter(
        status=AttendanceRecord.Status.ABSENT
    ).count()

    late_absent_occurrences = total_lates + total_absents

    # Only REGULAR employees get 15 days sick leave
    is_regular = employee.emp_status == Employee.EmpStatus.REGULAR
    if is_regular:
        sick_annual = 15  # fixed allocation
        # 4 lates/absences = 1 full day deducted
        sick_days_deducted = late_absent_occurrences // 4
        if sick_days_deducted > sick_annual:
            sick_days_deducted = sick_annual
        sick_remaining = sick_annual - sick_days_deducted
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

        "total_lates": total_lates,
        "total_absents": total_absents,
        "late_absent_occurrences": late_absent_occurrences,

        "is_regular": is_regular,
        "sick_annual": sick_annual,
        "sick_days_deducted": sick_days_deducted,
        "sick_remaining": sick_remaining,

        "pending_activities": pending_activities,
    }
    return render(request, "accounts/employeedash.html", context)

@login_required(login_url="employeelogin")
def payslip(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return redirect("employeedash")

    today = localdate()

    hire_date = employee.date_hired or today

    periods = get_half_month_periods(hire_date, today)

    current_start, current_end = get_current_period(today)

# Only add current period IF employee was already hired
    if hire_date <= current_end:
        current_period = (current_start, current_end)
        if current_period not in periods:
            periods.append(current_period)

# Always keep periods ordered
    periods.sort(key=lambda p: (p[0], p[1]))

    selected_value = request.GET.get("period")
    if selected_value:
        try:
            s_str, e_str = selected_value.split("_")
            selected_start = date.fromisoformat(s_str)
            selected_end = date.fromisoformat(e_str)
        except Exception:
            selected_start, selected_end = periods[-1]
    else:
        selected_start, selected_end = periods[-1]

    period_options = []
    selected_label = ""
    selected_period_value = f"{selected_start.isoformat()}_{selected_end.isoformat()}"

    for start, end in periods:
        value = f"{start}_{end}"
        label = f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"
        period_options.append({"value": value, "label": label})
        if value == selected_period_value:
            selected_label = label

    is_job_order = employee.emp_status == Employee.EmpStatus.JOB_ORDER

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

        rata = gsis = philhealth = pagibig = gsis_loan = Decimal("0")

    # ================= REGULAR =================
    else:
        # Extract SG number (SG-18 → 18)
        match = re.search(r"\d+", employee.salary_grade or "")
        sg_num = int(match.group()) if match else None

        salary_obj = SalaryGrade.objects.filter(grade=sg_num).first()
        monthly = salary_obj.monthly_salary if salary_obj else Decimal("0")

        if monthly == 0:
            messages.warning(
                request,
                f"Salary Grade SG-{sg_num} has no configured salary."
            )

        # Govt standard: 22 working days
        daily_rate = monthly / Decimal("22")

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

        rata = Decimal("2000.00")
        gsis = Decimal("1394.28")
        philhealth = Decimal("387.30")
        pagibig = Decimal("809.84")
        gsis_loan = Decimal("655.56")
        
    total_earnings = basic_salary + rata
    total_deductions = gsis + philhealth + pagibig + gsis_loan
    net_pay = total_earnings - total_deductions

    context = {
        "employee": employee,
        "period_options": period_options,
        "selected_period_value": selected_period_value,
        "selected_period_label": selected_label,
        "is_job_order": is_job_order,
        "basic_salary": basic_salary,
        "rata": rata,
        "gsis": gsis,
        "philhealth": philhealth,
        "pagibig": pagibig,
        "gsis_loan": gsis_loan,
        "total_earnings": total_earnings,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
        "daily_rate": daily_rate,
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
    return render(request, "employee_qr_scan.html")

from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone
from datetime import date, time

@require_POST
@login_required(login_url="employeelogin")
def employee_qr_scan(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return JsonResponse({"error": "Employee not found"}, status=404)

    today = date.today()
    now = timezone.localtime()  # Asia/Manila safe

    GRACE_LIMIT = time(8, 15)

    attendance, created = AttendanceRecord.objects.get_or_create(
        employee=employee,
        date=today,
    )

    # ✅ TIME-IN
    if attendance.time_in is None:
        attendance.time_in = now

        attendance.status = (
            AttendanceRecord.Status.LATE
            if now.time() > GRACE_LIMIT
            else AttendanceRecord.Status.PRESENT
        )

        attendance.save()

        return JsonResponse({
            "success": True,
            "action": "time_in",
            "time": attendance.time_in.strftime("%H:%M"),
        })

    # ✅ TIME-OUT
    if attendance.time_out is None:
        attendance.time_out = now
        delta = attendance.time_out - attendance.time_in
        attendance.hours_worked = round(delta.total_seconds() / 3600, 2)
        attendance.save()

        return JsonResponse({
            "success": True,
            "action": "time_out",
            "time": attendance.time_out.strftime("%H:%M"),
        })

    return JsonResponse({
        "error": "Attendance already completed"
    }, status=400)

