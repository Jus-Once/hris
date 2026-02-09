from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path("attendance/scan/", views.employee_qr_page, name="employee_qr_page"),
    path("attendance/scan/submit/", views.employee_qr_submit, name="employee_qr_submit"),

    path('adminlogin', views.adminlogin, name='adminlogin'),
    path('adminlogout', views.adminlogout, name='adminlogout'),
    path('employeelogin', views.employeelogin, name='employeelogin'),

    path('admindash', views.admindash, name='admindash'),
    path('adminemployee', views.adminemployee, name='adminemployee'),

    path('employees/', views.employee_list, name='employee_list'),
    path('time', views.time_tracking, name='time'),
    path('message', views.message_admin, name='message'),

    path('employees/<str:emp_id>/delete/', views.employee_delete, name='employee_delete'),
    path('employees/<str:emp_id>/archive/', views.employee_archive, name='employee_archive'),
    path('employees/<str:emp_id>/recover/', views.employee_recover, name='employee_recover'),
    path('employees/<str:emp_id>/reset-password/', views.employee_reset_password, name='employee_reset_password'),
    path('employees/<str:emp_id>/attendance-toggle/', views.employee_toggle_attendance, name='employee_toggle_attendance'),

    path('messages/<int:pk>/update/', views.message_update_status, name='message_update_status'),

    path('employeedash', views.employeedash, name='employeedash'),
    path('payslip', views.payslip, name='payslip'),
    path('benefits', views.benefits, name='benefits'),
    path('performance', views.performance, name='performance'),
    path('announcements', views.announcements, name='announcements'),
    path('help', views.help, name='help'),
    path('employee/profile', views.employee_profile, name='employee_profile'),
]
