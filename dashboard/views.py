from decimal import Decimal
from datetime import date

from django.shortcuts import redirect, render, get_object_or_404
from django.db import transaction
from django.db.models import Sum, Q, Max, Count
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator


from .models import (
    Account, AccountProfile, Wallet,
    Category, Product, ProductImage,
    Cart, CartItem,
    Order, OrderItem
)

# =========================
# Helpers
# =========================
def get_logged_in_account(request):
    account_id = request.session.get("account_id")
    if not account_id:
        return None
    return Account.objects.filter(id=account_id).first()


def build_common_ctx(account):
    """Context chung cho header"""
    if not account:
        return {"account": None, "balance": 0, "total_cart_item": 0}
    balance = account.wallet.balance if hasattr(account, "wallet") else 0
    total_cart_item = account.cart.quantity if hasattr(account, "cart") else 0
    return {"account": account, "balance": balance, "total_cart_item": total_cart_item}


def _recalc_cart_quantity(cart):
    cart.quantity = CartItem.objects.filter(cart=cart).aggregate(s=Sum("quantity"))["s"] or 0
    cart.save()


def _to_decimal(val, default="0"):
    try:
        return Decimal(str(val).strip())
    except Exception:
        return Decimal(default)


def _to_int(val, default=0):
    try:
        return int(val)
    except Exception:
        return default

def _admin_required(request):
    """
    Return: (account, resp)
    - resp != None => redirect response
    """
    account_id = request.session.get("account_id")
    if not account_id:
        return None, redirect("to_login_page")

    account = Account.objects.filter(id=account_id).first()
    if not account or account.role != "ADMIN":
        return None, redirect("dashboard")

    return account, None


def admin_categories(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    # nhận q hoặc keyword (đỡ bị lệch name input)
    q = (request.GET.get("q") or request.GET.get("keyword") or "").strip()

    # ✅ NOTE:
    # Nếu Product FK đến Category mà bạn có related_name="product" thì Count("product") OK.
    # Nếu không set related_name thì phải là "product_set".
    # Mình làm kiểu “tự đoán” để không bị lỗi.
    accessor = "product"
    try:
        Category._meta.get_field(accessor)
        # nếu Category có field tên product thì thôi (hiếm)
    except Exception:
        # kiểm tra related accessor thực tế
        rel_names = [r.get_accessor_name() for r in Category._meta.related_objects]
        if "product" in rel_names:
            accessor = "product"
        elif "product_set" in rel_names:
            accessor = "product_set"
        elif "products" in rel_names:
            accessor = "products"

    qs = Category.objects.all()

    # annotate đếm sản phẩm (nếu accessor tồn tại)
    try:
        qs = qs.annotate(product_count=Count(accessor))
    except Exception:
        # nếu annotate fail thì thôi, vẫn list bình thường
        pass

    if q:
        qs = qs.filter(category_name__icontains=q)

    # ✅ mặc định show mới nhất lên đầu (đỡ hiểu nhầm ID “bị đảo”)
    qs = qs.order_by("-category_id")

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    ctx = build_common_ctx(account)
    ctx.update({
        "page_obj": page_obj,
        "q": q,
    })
    return render(request, "dashboard/admin_categories.html", ctx)


def admin_category_create(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    if request.method == "GET":
        ctx = build_common_ctx(account)
        return render(request, "dashboard/admin_category_create.html", ctx)

    name = (request.POST.get("category_name") or "").strip()

    if not name:
        ctx = build_common_ctx(account)
        ctx["error_message"] = "Vui lòng nhập tên danh mục."
        return render(request, "dashboard/admin_category_create.html", ctx)

    if Category.objects.filter(category_name__iexact=name).exists():
        ctx = build_common_ctx(account)
        ctx["error_message"] = "Danh mục này đã tồn tại."
        return render(request, "dashboard/admin_category_create.html", ctx)

    Category.objects.create(category_name=name, quantity=0)
    return redirect("admin_categories")


def admin_category_edit(request, category_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    c = get_object_or_404(Category, category_id=category_id)

    if request.method == "GET":
        ctx = build_common_ctx(account)
        ctx.update({"c": c})
        return render(request, "dashboard/admin_category_edit.html", ctx)

    name = (request.POST.get("category_name") or "").strip()
    if not name:
        ctx = build_common_ctx(account)
        ctx.update({"c": c, "error_message": "Tên danh mục không được để trống."})
        return render(request, "dashboard/admin_category_edit.html", ctx)

    if Category.objects.filter(category_name__iexact=name).exclude(category_id=c.category_id).exists():
        ctx = build_common_ctx(account)
        ctx.update({"c": c, "error_message": "Tên danh mục đã tồn tại."})
        return render(request, "dashboard/admin_category_edit.html", ctx)

    c.category_name = name
    c.save()
    return redirect("admin_categories")


def admin_category_delete(request, category_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    c = get_object_or_404(Category, category_id=category_id)

    # chặn xóa nếu có sản phẩm
    if Product.objects.filter(category=c).exists():
        return redirect("admin_categories")

    if request.method == "POST":
        c.delete()
    return redirect("admin_categories")

# =========================
# Dashboard / Home
# =========================
def dashboard(request):
    account = get_logged_in_account(request)
    ctx = build_common_ctx(account)

    q = (request.GET.get("q") or "").strip()

    qs = Product.objects.select_related("category").order_by("-product_id")
    if q:
        qs = qs.filter(
            Q(product_name__icontains=q)
            | Q(description__icontains=q)
            | Q(category__category_name__icontains=q)
        )
        products = qs[:40]
        search_count = qs.count()
    else:
        products = qs[:8]
        search_count = 0

    ctx.update({
        "products": products,
        "q": q,
        "search_count": search_count,
    })
    return render(request, "dashboard/dashboard.html", ctx)


# =========================
# Admin page (tabs)
# =========================
def to_admin_page(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    categories = Category.objects.all().order_by("category_name")
    products = Product.objects.select_related("category").order_by("-product_id")
    orders = Order.objects.select_related("account").order_by("-created_at")[:10]

    if request.method == "POST":
        name = (request.POST.get("product_name") or "").strip()
        price = _to_decimal(request.POST.get("price") or "0")
        category_id = request.POST.get("category_id")
        desc = (request.POST.get("description") or "").strip()
        image = request.FILES.get("image")

        is_genuine = (request.POST.get("is_genuine") == "on")
        is_fast_ship = (request.POST.get("is_fast_ship") == "on")

        hint_text = (request.POST.get("hint_text") or "").strip()
        storage_short = (request.POST.get("storage_short") or "").strip()
        return_policy = (request.POST.get("return_policy") or "").strip()
        storage_guide = (request.POST.get("storage_guide") or "").strip()

        energy_kcal = _to_int(request.POST.get("energy_kcal"), 0)
        protein_g = _to_decimal(request.POST.get("protein_g") or "0")
        fat_g = _to_decimal(request.POST.get("fat_g") or "0")
        carb_g = _to_decimal(request.POST.get("carb_g") or "0")

        gallery_files = request.FILES.getlist("gallery_images")

        if not name or price <= 0 or not category_id or not image:
            return render(request, "dashboard/admin_page.html", {
                "account": account,
                "categories": categories,
                "products": products,
                "orders": orders,
                "error_message": "Vui lòng nhập đủ: Tên, Giá (>0), Danh mục, Ảnh."
            })

        category = Category.objects.filter(category_id=category_id).first()
        if not category:
            return render(request, "dashboard/admin_page.html", {
                "account": account,
                "categories": categories,
                "products": products,
                "orders": orders,
                "error_message": "Danh mục không hợp lệ."
            })

        with transaction.atomic():
            p = Product.objects.create(
                product_name=name,
                price=price,
                category=category,
                image=image,
                description=desc or "mô tả",

                is_genuine=is_genuine,
                is_fast_ship=is_fast_ship,

                hint_text=hint_text or "Uống ngon hơn khi lạnh",
                storage_short=storage_short or "Nơi khô ráo, thoáng mát",
                return_policy=return_policy or "7 ngày nếu lỗi",
                storage_guide=storage_guide or "Bảo quản nơi khô ráo và thoáng mát.\nĐóng kín sau khi mở.\nNgon hơn khi uống lạnh.",

                energy_kcal=energy_kcal,
                protein_g=protein_g,
                fat_g=fat_g,
                carb_g=carb_g,
            )

            for idx, f in enumerate(gallery_files, start=1):
                ProductImage.objects.create(product=p, image=f, sort_order=idx)

        return redirect("to_admin_page")

    return render(request, "dashboard/admin_page.html", {
        "account": account,
        "categories": categories,
        "products": products,
        "orders": orders,
    })


# =========================
# Cart
# =========================
def to_view_cart(request):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    cart = get_object_or_404(Cart, account=account)
    cart_items = CartItem.objects.filter(cart=cart).select_related("product", "product__category")

    total = Decimal("0")
    for item in cart_items:
        item.subtotal = item.product.price * item.quantity
        total += item.subtotal

    ctx = build_common_ctx(account)
    ctx.update({"cart_items": cart_items, "cart_total": total})
    return render(request, "dashboard/view_cart.html", ctx)


def add_to_cart(request, product_id):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    product = get_object_or_404(Product, product_id=product_id)
    cart, _ = Cart.objects.get_or_create(account=account, defaults={"quantity": 0})

    item = CartItem.objects.filter(cart=cart, product=product).first()
    if item:
        item.quantity += 1
        item.save()
    else:
        CartItem.objects.create(cart=cart, product=product, quantity=1)

    _recalc_cart_quantity(cart)
    return redirect("to_view_cart")


def cart_inc(request, product_id):
    return add_to_cart(request, product_id)


def cart_dec(request, product_id):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    cart = get_object_or_404(Cart, account=account)
    product = get_object_or_404(Product, product_id=product_id)

    item = CartItem.objects.filter(cart=cart, product=product).first()
    if item:
        item.quantity -= 1
        if item.quantity <= 0:
            item.delete()
        else:
            item.save()

    _recalc_cart_quantity(cart)
    return redirect("to_view_cart")


def cart_remove(request, product_id):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    cart = get_object_or_404(Cart, account=account)
    product = get_object_or_404(Product, product_id=product_id)

    CartItem.objects.filter(cart=cart, product=product).delete()
    _recalc_cart_quantity(cart)
    return redirect("to_view_cart")


# =========================
# Auth
# =========================
def to_login_page(request):
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = (request.POST.get("password") or "").strip()

        user = Account.objects.filter(username=username, password=password).first()
        if not user:
            return render(request, "dashboard/login_page.html", {
                "error_message": "Tên đăng nhập hoặc mật khẩu không đúng."
            })

        if getattr(user, "status", "normal") != "normal":
            return render(request, "dashboard/login_page.html", {
                "error_message": "Tài khoản đang bị khóa, vui lòng liên hệ admin để biết thêm chi tiết"
            })

        request.session["account_id"] = user.id
        request.session["username"] = user.username
        request.session["role"] = user.role
        request.session["status"] = getattr(user, "status", "normal")
        return redirect("dashboard")

    return render(request, "dashboard/login_page.html")


def to_register_page(request):
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = (request.POST.get("password") or "").strip()
        confirm_password = (request.POST.get("confirm_password") or "").strip()

        if password != confirm_password:
            return render(request, "dashboard/register_page.html", {
                "error_message": "Mật khẩu không trùng nhau"
            })

        if Account.objects.filter(username=username).exists():
            return render(request, "dashboard/register_page.html", {
                "error_message": "Tên đăng nhập đã tồn tại."
            })

        account = Account.objects.create(username=username, password=password)

        AccountProfile.objects.create(
            account=account,
            full_name="Chưa có",
            date_of_birth=date(2025, 1, 1),
            email=f"{username}@gmail.com",
            phone_number="0123456789"
        )

        Cart.objects.create(account=account, quantity=0)
        Wallet.objects.create(account=account, balance=0)

        return render(request, "dashboard/register_page.html", {
            "success_message": "Đăng kí thành công. Vui lòng đăng nhập."
        })

    return render(request, "dashboard/register_page.html")


def logout(request):
    request.session.flush()
    return redirect("dashboard")


# =========================
# Checkout / Orders (User)
# =========================
def checkout(request):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    cart = get_object_or_404(Cart, account=account)
    cart_items = CartItem.objects.filter(cart=cart).select_related("product", "product__category")

    total = Decimal("0")
    for item in cart_items:
        total += (item.product.price * item.quantity)

    if request.method == "GET":
        ctx = build_common_ctx(account)
        ctx.update({
            "cart_items": cart_items,
            "cart_total": total,
            "receiver_name": "",
            "receiver_phone": "",
            "receiver_address": "",
        })
        return render(request, "dashboard/checkout.html", ctx)

    receiver_name = (request.POST.get("receiver_name") or "").strip()
    receiver_phone = (request.POST.get("receiver_phone") or "").strip()
    receiver_address = (request.POST.get("receiver_address") or "").strip()

    def _render_error(msg, balance_override=None):
        ctx = build_common_ctx(account)
        ctx.update({
            "cart_items": cart_items,
            "cart_total": total,
            "error_message": msg,
            "receiver_name": receiver_name,
            "receiver_phone": receiver_phone,
            "receiver_address": receiver_address,
        })
        if balance_override is not None:
            ctx["balance"] = balance_override
        return render(request, "dashboard/checkout.html", ctx)

    if total <= 0:
        return _render_error("Giỏ hàng đang trống.")
    if not receiver_name or not receiver_phone or not receiver_address:
        return _render_error("Vui lòng nhập đủ Họ tên, SĐT và Địa chỉ.")

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(account=account)
        if wallet.balance < total:
            return _render_error("Số dư ví không đủ để thanh toán.", balance_override=wallet.balance)

        wallet.balance = wallet.balance - total
        wallet.save()

        order = Order.objects.create(
            account=account,
            total_amount=total,
            status="PAID",
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            receiver_address=receiver_address
        )

        for item in cart_items:
            img_name = item.product.image.name if (item.product and item.product.image) else ""
            OrderItem.objects.create(
                order=order,
                product=item.product,
                product_name=item.product.product_name,
                unit_price=item.product.price,
                quantity=item.quantity,
                product_image_name=img_name
            )

        cart_items.delete()
        cart.quantity = 0
        cart.save()

    return redirect("order_detail", order_id=order.order_id)


def my_orders(request):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    orders = Order.objects.filter(account=account).order_by("-created_at")
    ctx = build_common_ctx(account)
    ctx.update({"orders": orders})
    return render(request, "dashboard/orders.html", ctx)


def order_detail(request, order_id):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    order = get_object_or_404(Order, order_id=order_id, account=account)
    items = list(order.items.all())

    grand_total = Decimal("0")
    for it in items:
        it.line_total = (it.unit_price * it.quantity)
        grand_total += it.line_total

    ctx = build_common_ctx(account)
    ctx.update({"order": order, "items": items, "grand_total": grand_total})
    return render(request, "dashboard/order_detail.html", ctx)


# =========================
# Wallet
# =========================
def wallet_topup(request):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    wallet, _ = Wallet.objects.get_or_create(account=account, defaults={"balance": 0})

    if request.method == "POST":
        amount_str = (request.POST.get("amount") or "").strip()
        try:
            amount = Decimal(amount_str)
        except Exception:
            ctx = build_common_ctx(account)
            ctx.update({"error_message": "Số tiền không hợp lệ."})
            return render(request, "dashboard/wallet_topup.html", ctx)

        if amount <= 0:
            ctx = build_common_ctx(account)
            ctx.update({"error_message": "Số tiền phải lớn hơn 0."})
            return render(request, "dashboard/wallet_topup.html", ctx)

        wallet.balance = wallet.balance + amount
        wallet.save()
        return redirect("dashboard")

    ctx = build_common_ctx(account)
    return render(request, "dashboard/wallet_topup.html", ctx)


# =========================
# Product Detail (User)
# =========================
def product_detail(request, product_id):
    p = get_object_or_404(Product.objects.select_related("category"), product_id=product_id)

    account = get_logged_in_account(request)
    ctx = build_common_ctx(account)

    related = (
        Product.objects
        .filter(category=p.category)
        .exclude(product_id=p.product_id)
        .order_by("-product_id")[:4]
    )

    # nếu bạn muốn show ảnh phụ ở trang detail thì fetch thêm:
    gallery = p.gallery.all().order_by("sort_order", "id")

    ctx.update({"p": p, "related": related, "gallery": gallery})
    return render(request, "dashboard/product_detail.html", ctx)


# =========================
# Admin Orders
# =========================
def admin_orders(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    orders = Order.objects.select_related("account").order_by("-created_at")
    ctx = build_common_ctx(account)
    ctx.update({"orders": orders})
    return render(request, "dashboard/admin_orders.html", ctx)


def admin_order_detail(request, order_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    order = get_object_or_404(Order, order_id=order_id)
    items = OrderItem.objects.filter(order=order).select_related("product").order_by("id")

    ctx = build_common_ctx(account)
    ctx.update({"order": order, "items": items})
    return render(request, "dashboard/admin_order_detail.html", ctx)


@require_POST
def admin_order_update_status(request, order_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    order = get_object_or_404(Order, order_id=order_id)

    new_status = (request.POST.get("status") or "").strip().upper()
    allowed = {"PAID", "PENDING", "FAILED", "CANCELLED"}

    if new_status in allowed:
        order.status = new_status
        order.save()

    return redirect("admin_order_detail", order_id=order.order_id)


# =========================
# Admin Products (List/Create/Edit/Delete)
# =========================
def admin_products(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    categories = Category.objects.all().order_by("category_name")

    q = (request.GET.get("q") or "").strip()
    cat = (request.GET.get("cat") or "").strip()
    sort = (request.GET.get("sort") or "new").strip()

    qs = Product.objects.select_related("category").all()

    if q:
        qs = qs.filter(product_name__icontains=q)

    if cat:
        qs = qs.filter(category_id=cat)

    if sort == "price_asc":
        qs = qs.order_by("price")
    elif sort == "price_desc":
        qs = qs.order_by("-price")
    else:
        qs = qs.order_by("-product_id")

    paginator = Paginator(qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "dashboard/admin_products.html", {
        "account": account,
        "categories": categories,
        "page_obj": page_obj,
        "q": q,
        "cat": cat,
        "sort": sort,
    })


def admin_product_create(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    categories = Category.objects.all().order_by("category_name")

    if request.method == "GET":
        return render(request, "dashboard/admin_product_create.html", {
            "account": account,
            "categories": categories,
        })

    name = (request.POST.get("product_name") or "").strip()
    price = _to_decimal(request.POST.get("price") or "0")
    category_id = request.POST.get("category_id")
    desc = (request.POST.get("description") or "").strip()
    image = request.FILES.get("image")  # có thể None nếu bạn cho phép

    is_genuine = (request.POST.get("is_genuine") == "on")
    is_fast_ship = (request.POST.get("is_fast_ship") == "on")

    hint_text = (request.POST.get("hint_text") or "").strip()
    storage_short = (request.POST.get("storage_short") or "").strip()
    return_policy = (request.POST.get("return_policy") or "").strip()
    storage_guide = (request.POST.get("storage_guide") or "").strip()

    energy_kcal = _to_int(request.POST.get("energy_kcal"), 0)
    protein_g = _to_decimal(request.POST.get("protein_g") or "0")
    fat_g = _to_decimal(request.POST.get("fat_g") or "0")
    carb_g = _to_decimal(request.POST.get("carb_g") or "0")

    gallery_files = request.FILES.getlist("gallery_images")

    if not name or price <= 0 or not category_id:
        return render(request, "dashboard/admin_product_create.html", {
            "account": account,
            "categories": categories,
            "error_message": "Vui lòng nhập đủ: Tên, Giá (>0), Danh mục.",
        })

    category = Category.objects.filter(category_id=category_id).first()
    if not category:
        return render(request, "dashboard/admin_product_create.html", {
            "account": account,
            "categories": categories,
            "error_message": "Danh mục không hợp lệ.",
        })

    with transaction.atomic():
        p = Product.objects.create(
            product_name=name,
            price=price,
            category=category,
            image=image,
            description=desc,

            is_genuine=is_genuine,
            is_fast_ship=is_fast_ship,

            hint_text=hint_text or "Uống ngon hơn khi lạnh",
            storage_short=storage_short or "Nơi khô ráo, thoáng mát",
            return_policy=return_policy or "7 ngày nếu lỗi",
            storage_guide=storage_guide or "Bảo quản nơi khô ráo và thoáng mát.\nĐóng kín sau khi mở.\nNgon hơn khi uống lạnh.",

            energy_kcal=energy_kcal,
            protein_g=protein_g,
            fat_g=fat_g,
            carb_g=carb_g,
        )

        for idx, f in enumerate(gallery_files, start=1):
            ProductImage.objects.create(product=p, image=f, sort_order=idx)

    return redirect("admin_products")


def admin_product_edit(request, product_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    categories = Category.objects.all().order_by("category_name")
    p = get_object_or_404(Product, product_id=product_id)
    gallery = p.gallery.all().order_by("sort_order", "id")

    if request.method == "GET":
        return render(request, "dashboard/admin_product_edit.html", {
            "account": account,
            "categories": categories,
            "p": p,
            "gallery": gallery,
        })

    name = (request.POST.get("product_name") or "").strip()
    price = _to_decimal(request.POST.get("price") or "0")
    category_id = request.POST.get("category_id")
    desc = (request.POST.get("description") or "").strip()

    image = request.FILES.get("image")  # optional

    is_genuine = (request.POST.get("is_genuine") == "on")
    is_fast_ship = (request.POST.get("is_fast_ship") == "on")

    hint_text = (request.POST.get("hint_text") or "").strip()
    storage_short = (request.POST.get("storage_short") or "").strip()
    return_policy = (request.POST.get("return_policy") or "").strip()
    storage_guide = (request.POST.get("storage_guide") or "").strip()

    energy_kcal = _to_int(request.POST.get("energy_kcal"), 0)
    protein_g = _to_decimal(request.POST.get("protein_g") or "0")
    fat_g = _to_decimal(request.POST.get("fat_g") or "0")
    carb_g = _to_decimal(request.POST.get("carb_g") or "0")

    gallery_files = request.FILES.getlist("gallery_images")
    delete_gallery_ids = request.POST.getlist("delete_gallery")

    if not name or price <= 0 or not category_id:
        return render(request, "dashboard/admin_product_edit.html", {
            "account": account,
            "categories": categories,
            "p": p,
            "gallery": gallery,
            "error_message": "Vui lòng nhập đủ: Tên, Giá (>0), Danh mục.",
        })

    category = Category.objects.filter(category_id=category_id).first()
    if not category:
        return render(request, "dashboard/admin_product_edit.html", {
            "account": account,
            "categories": categories,
            "p": p,
            "gallery": gallery,
            "error_message": "Danh mục không hợp lệ.",
        })

    with transaction.atomic():
        p.product_name = name
        p.price = price
        p.category = category
        p.description = desc

        if image:
            p.image = image

        p.is_genuine = is_genuine
        p.is_fast_ship = is_fast_ship
        p.hint_text = hint_text or p.hint_text
        p.storage_short = storage_short or p.storage_short
        p.return_policy = return_policy or p.return_policy
        p.storage_guide = storage_guide or p.storage_guide

        p.energy_kcal = energy_kcal
        p.protein_g = protein_g
        p.fat_g = fat_g
        p.carb_g = carb_g
        p.save()

        if delete_gallery_ids:
            ProductImage.objects.filter(product=p, id__in=delete_gallery_ids).delete()

        max_order = ProductImage.objects.filter(product=p).aggregate(mx=Max("sort_order")).get("mx") or 0
        order = max_order
        for f in gallery_files:
            order += 1
            ProductImage.objects.create(product=p, image=f, sort_order=order)

    return redirect("admin_products")


def admin_product_delete(request, product_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    p = get_object_or_404(Product, product_id=product_id)

    if request.method == "POST":
        p.delete()
        return redirect("admin_products")

    return redirect("admin_products")
