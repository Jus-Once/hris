from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),

    path('adminlogin', views.adminlogin, name='adminlogin'),
    path('adminlogout', views.adminlogout, name='adminlogout'),
    path('employeelogin', views.employeelogin, name='employeelogin'),

    path('admindash', views.admindash, name='admindash'),
    path('adminemployee', views.adminemployee, name='adminemployee'),
    path('time', views.time_tracking, name='time'),
    path('message', views.message_admin, name='message'),

    path('employees/<str:emp_id>/delete/', views.employee_delete, name='employee_delete'),
    path('messages/<int:pk>/update/', views.message_update_status, name='message_update_status'),

    path('employeedash', views.employeedash, name='employeedash'),
    path('payslip', views.payslip, name='payslip'),
    path('benefits', views.benefits, name='benefits'),
    path('performance', views.performance, name='performance'),
    path('announcements', views.announcements, name='announcements'),
    path('help', views.help, name='help'),
    path('employee/profile', views.employee_profile, name='employee_profile'),
]