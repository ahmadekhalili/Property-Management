from django.urls import path

from . import views

app_name = 'main'

urlpatterns = [
    path('', views.Home.as_view(), name='home'),
    path('index/', views.index.as_view(), name='index'),
    path('sms_code_divar/', views.SmsCode.as_view(), name='sms-code-divar'),
    path('login_divar/', views.LoginDivar.as_view(), name='login-divar'),
    path('crawl_files/', views.FileCrawl.as_view(), name='crawl-files'),
    path('files/', views.FileList.as_view(), name='file-list'),
    path('files/<int:page>/', views.FileList.as_view(), name='file-list-page'),
    path('files/<id>/', views.FileDetail.as_view(), name='file-detail'),
]
