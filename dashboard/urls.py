from django.urls import path
from .views import  *

urlpatterns = [
    path('', dashboard, name='dashboard'),  # URL rỗng trong app
    path('admin-page/', to_admin_page, name='to_admin_page'),  # URL cho trang admin
    path('view_cart/', to_view_cart, name='to_view_cart'),
    path('login/', to_login_page, name='to_login_page'),
    path('register/', to_register_page, name='to_register_page'),
    path('logout/', logout, name='logout'),
]