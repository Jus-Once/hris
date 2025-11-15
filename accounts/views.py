from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Avg
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_protect
from django.utils.timezone import localdate
from django.contrib.auth.models import User

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


def home(request):
    latest_announcements = Announcement.objects.filter(is_active=True)[:3]
    return render(request, 'accounts/home.html', {
        "announcements": latest_announcements,
    })


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
            return redirect('admindash')
        else:
            error = "Invalid credentials or you are not authorized as an admin."
            return render(request, 'accounts/adminlogin.html', {"error": error})

    return render(request, 'accounts/adminlogin.html')


@login_required
def adminlogout(request):
    logout(request)
    return redirect('adminlogin')


@csrf_protect
def employeelogin(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user is not None and not user.is_staff:
            login(request, user)
            return redirect('employeedash')
        else:
            error = "Invalid credentials or account is not an employee account."
            return render(request, 'accounts/employeelogin.html', {"error": error})

    return render(request, 'accounts/employeelogin.html')


@login_required
@user_passes_test(_is_admin)
def admindash(request):
    employee_count = Employee.objects.count()
    pending_messages_count = Message.objects.filter(status=Message.Status.PENDING).count()

    today = localdate()
    today_records = AttendanceRecord.objects.filter(date=today)

    present = today_records.filter(status=AttendanceRecord.Status.PRESENT).count()
    late = today_records.filter(status=AttendanceRecord.Status.LATE).count()
    absent = today_records.filter(status=AttendanceRecord.Status.ABSENT).count()
    fieldwork = today_records.filter(status=AttendanceRecord.Status.FIELDWORK).count()
    health = today_records.filter(status=AttendanceRecord.Status.HEALTH).count()

    total = present + late + absent + fieldwork + health
    total = total or 1

    def pct(x):
        return int((x / total) * 100)

    context = {
        "employee_count": employee_count,
        "pending_messages_count": pending_messages_count,
        "present": present,
        "late": late,
        "absent": absent,
        "fieldwork": fieldwork,
        "health": health,
        "total_att": total,
        "present_pct": pct(present),
        "late_pct": pct(late),
        "absent_pct": pct(absent),
        "fieldwork_pct": pct(fieldwork),
        "health_pct": pct(health),
    }
    return render(request, 'accounts/admindash.html', context)


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def adminemployee(request):
    q = request.GET.get("q", "").strip()
    dept = request.GET.get("dept", "").strip()
    status = request.GET.get("status", "").strip()

    employees = Employee.objects.all()

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

    show_form = request.GET.get("add") == "1"

    if request.method == "POST":
        data = request.POST
        emp_id = data.get("emp_id")

        emp = Employee(
            emp_id=emp_id,
            fname=data.get("fname"),
            lname=data.get("lname"),
            email=data.get("email"),
            phone=data.get("phone") or "",
            position=data.get("position") or "",
            dept=data.get("department") or "",
            salary_grade=data.get("salary_grade") or "",
            civil_status=data.get("civil_status") or None,
            emp_status=data.get("employment_status"),
            address=data.get("street") or "",
            brgy=data.get("barangay") or "",
            city=data.get("municipality") or "",
            province=data.get("province") or "",
            zipcode=data.get("zip") or "",
            emc_name=data.get("contactName") or "",
            emc_relation=data.get("relationship") or "",
            emc_phone=data.get("contactPhone") or "",
        )

        dob = data.get("birthday")
        hired = data.get("dateHired")
        if dob:
            emp.dob = dob
        if hired:
            emp.date_hired = hired

        emp.save()

        if emp_id and not User.objects.filter(username=emp_id).exists():
            default_password = emp_id
            user = User.objects.create_user(
                username=emp_id,
                password=default_password,
                first_name=emp.fname,
                last_name=emp.lname,
                email=emp.email,
            )
            emp.user = user
            emp.save()

        return redirect('adminemployee')

    dept_choices = Employee.objects.order_by().values_list('dept', flat=True).distinct()
    status_choices = Employee.EmpStatus.choices

    context = {
        "employees": employees,
        "q": q,
        "dept": dept,
        "status": status,
        "dept_choices": dept_choices,
        "status_choices": status_choices,
        "show_form": show_form,
    }
    return render(request, 'accounts/adminemployee.html', context)


@login_required
@user_passes_test(_is_admin)
@csrf_protect
def employee_delete(request, emp_id):
    employee = get_object_or_404(Employee, pk=emp_id)
    if request.method == "POST":
        if employee.user:
            employee.user.delete()
        employee.delete()
        return redirect('adminemployee')
    return render(request, 'accounts/employee_confirm_delete.html', {"employee": employee})


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
    return render(request, 'accounts/time.html', context)


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
            return redirect('message')

        if form_type == "announcement":
            title = request.POST.get("annTitle", "").strip()
            date = request.POST.get("annDate") or None
            body = request.POST.get("annBody", "").strip()
            if title and body:
                Announcement.objects.create(title=title, body=body, date=date)
            return redirect('message')

    messages_qs = Message.objects.all()
    faqs = FAQ.objects.filter(is_active=True)
    announcements = Announcement.objects.filter(is_active=True)

    context = {
        "messages": messages_qs,
        "faqs": faqs,
        "announcements": announcements,
    }
    return render(request, 'accounts/message.html', context)


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
    return redirect('message')


def _get_employee_from_user(user):
    if not user.is_authenticated:
        return None
    return getattr(user, "employee_profile", None)


@login_required(login_url='employeelogin')
def employeedash(request):
    employee = _get_employee_from_user(request.user)
    anns = Announcement.objects.filter(is_active=True)[:5]

    today = localdate()
    today_rec = None
    if employee:
        today_rec = AttendanceRecord.objects.filter(employee=employee, date=today).first()

    context = {
        "employee": employee,
        "announcements": anns,
        "today_attendance": today_rec,
    }
    return render(request, 'accounts/employeedash.html', context)


@login_required(login_url='employeelogin')
def payslip(request):
    employee = _get_employee_from_user(request.user)
    return render(request, 'accounts/payslip.html', {"employee": employee})


@login_required(login_url='employeelogin')
def benefits(request):
    employee = _get_employee_from_user(request.user)
    return render(request, 'accounts/benefits.html', {"employee": employee})


@login_required(login_url='employeelogin')
def performance(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return redirect('employeedash')

    okrs = EmployeePerformance.objects.filter(
        employee=employee,
        is_active=True,
    ).order_by('-created_at')[:10]

    weekly_summary = WeeklyPerformanceSummary.objects.filter(
        employee=employee,
    ).order_by('-week_start').first()

    weekly_activities = weekly_summary.activities.all() if weekly_summary else []

    context = {
        "employee": employee,
        "okrs": okrs,
        "weekly_summary": weekly_summary,
        "weekly_activities": weekly_activities,
    }
    return render(request, 'accounts/performance.html', context)


@login_required(login_url='employeelogin')
def announcements(request):
    employee = _get_employee_from_user(request.user)
    anns = Announcement.objects.filter(is_active=True)
    return render(request, 'accounts/announcements.html', {
        "employee": employee,
        "announcements": anns,
    })


@login_required(login_url='employeelogin')
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
    return render(request, 'accounts/help.html', context)


@login_required(login_url='employeelogin')
@csrf_protect
def employee_profile(request):
    employee = _get_employee_from_user(request.user)
    if not employee:
        return redirect('employeedash')

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
                    password=new_pwd1
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
    return render(request, 'accounts/employee_profile.html', context)