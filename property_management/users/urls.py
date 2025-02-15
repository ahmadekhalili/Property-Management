from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from . import views

app_name = 'users'

urlpatterns = [
    path('token/', views.TokenObtainPairViewCustom.as_view(), name='token_obtain_pair'),  # Login
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),  # Refresh token
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),  # Verify token

    path('login/', views.LogIn.as_view(), name='loginview'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('sendsms/', views.SendSMS.as_view(), name='sendsms'),
    path('signup/', views.SignUp.as_view(), name='signupview'),
    path('signup/<int:pk>/', views.SignUp.as_view(), name='signup-update'),
    path('signuptest/', views.TestSignUp.as_view(), name='signup-test'),
    path('update/', views.UserUpdate.as_view(), name='user-change'),
    path('profile/<user_id>/', views.UserProfile.as_view(), name='user-profile'),
    path('profile/admin/<int:pk>/', views.AdminProfile.as_view(), name='admin-profile'),     #we used this url for main/my_serializers/PostMongoSerializer.author
]
