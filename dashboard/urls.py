from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('admin-page/', views.to_admin_page, name='to_admin_page'),

    # ✅ NEW: products admin pages
    path('admin-page/products/', views.admin_products, name='admin_products'),
    path('admin-page/products/create/', views.admin_product_create, name='admin_product_create'),
    path('admin-page/products/<int:product_id>/edit/', views.admin_product_edit, name='admin_product_edit'),
    path('admin-page/products/<int:product_id>/delete/', views.admin_product_delete, name='admin_product_delete'),
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),


    path('view_cart/', views.to_view_cart, name='to_view_cart'),
    path('add_to_cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),

    path('cart/inc/<int:product_id>/', views.cart_inc, name='cart_inc'),
    path('cart/dec/<int:product_id>/', views.cart_dec, name='cart_dec'),
    path('cart/remove/<int:product_id>/', views.cart_remove, name='cart_remove'),

    path('checkout/', views.checkout, name='checkout'),

    path('my_orders/', views.my_orders, name='my_orders'),
    path('order/<int:order_id>/', views.order_detail, name='order_detail'),

    path('wallet/topup/', views.wallet_topup, name='wallet_topup'),

    path('login/', views.to_login_page, name='to_login_page'),
    path('register/', views.to_register_page, name='to_register_page'),
    path('logout/', views.logout, name='logout'),

    path('admin-page/orders/', views.admin_orders, name='admin_orders'),
    path('admin-page/orders/<int:order_id>/', views.admin_order_detail, name='admin_order_detail'),
    path('admin-page/orders/<int:order_id>/status/', views.admin_order_update_status, name='admin_order_update_status'),

    path("admin-page/categories/", views.admin_categories, name="admin_categories"),
    path("admin-page/categories/create/", views.admin_category_create, name="admin_category_create"),
    path("admin-page/categories/<int:category_id>/edit/", views.admin_category_edit, name="admin_category_edit"),
    path("admin-page/categories/<int:category_id>/delete/", views.admin_category_delete, name="admin_category_delete"),

    path("admin-page/users/", views.admin_users, name="admin_users"),
    path("admin-page/users/create/", views.admin_user_create, name="admin_user_create"),
    path("admin-page/users/<int:user_id>/edit/", views.admin_user_edit, name="admin_user_edit"),
    path("admin-page/users/<int:user_id>/toggle/", views.admin_user_toggle, name="admin_user_toggle"),
    path("admin-page/users/<int:user_id>/delete/", views.admin_user_delete, name="admin_user_delete"),

]
