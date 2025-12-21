from django.shortcuts import redirect, render
from .models import  *
from datetime import date
# Create your views here.
def dashboard(request):
    if not request.session.get('account_id'):
        return render(request, 'dashboard/dashboard.html')
    else:
        account_id = request.session.get('account_id')
        account = Account.objects.get(id = account_id)
        wallet_balance = account.wallet.balance

        total_cart_item = account.cart.quantity
        return render(request, 'dashboard/dashboard.html', {
            'account': account,
            'balance': wallet_balance,
            'total_cart_item': total_cart_item
        })

def to_admin_page(request):
    return render(request, 'dashboard/admin_page.html')

def to_view_cart(request):
    if not request.session.get('account_id'):
        return render(request, 'dashboard/login_page.html')

    account_id = request.session.get('account_id')
    account = Account.objects.get(id=account_id)
    cart = account.cart
    cart_items = CartItem.objects.filter(cart=cart).select_related('product')
    for item in cart_items:
        item.subtotal = item.product.price * item.quantity
    return render(request, 'dashboard/view_cart.html', {
        'cart_items': cart_items
    })

def to_login_page(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = Account.objects.filter(username=username, password=password).first()
        if user:
            if user.status != "normal":
                error_message = "Tài khoản đang bị khóa, vui lòng liên hệ admin để biết thêm chi tiết"
                return render(request, 'dashboard/login_page.html', {'error_message': error_message})
            else:        
                request.session['account_id'] = user.id
                request.session['username'] = user.username
                request.session['password'] = user.password
                request.session['role'] = user.role
                request.session['status'] = user.status
                return redirect('dashboard')
        else:
            error_message = "Tên đăng nhập hoặc mật khẩu không đúng."
            return render(request, 'dashboard/login_page.html', {'error_message': error_message})
    return render(request, 'dashboard/login_page.html')

def to_register_page(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        if(password != confirm_password):
            error_message = "Mật khẩu không trùng nhau"
            return render(request, 'dashboard/register_page.html', {'error_message': error_message})
        if Account.objects.filter(username=username).exists():
            error_message = "Tên đăng nhập đã tồn tại."
            return render(request, 'dashboard/register_page.html', {'error_message': error_message})
        account = Account.objects.create(
            username = username,
            password = password,
        )

        AccountProfile.objects.create(
            account = account,
            full_name = "Chưa có",
            date_of_birth = date(2025, 1, 1),
            email = f"this is {username}@gmail.com",
            phone_number = "0123456789"
        )

        Cart.objects.create(
            account = account
        )

        Wallet.objects.create(
            account = account
        )
        return render(request, 'dashboard/register_page.html', {'success_message': "Đăng kí thành công. Vui lòng đăng nhập."})
    return render(request, 'dashboard/register_page.html')

def logout(request):
    request.session.flush()   
    return render(request, 'dashboard/dashboard.html')