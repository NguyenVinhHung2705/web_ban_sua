from decimal import Decimal
from datetime import date

from django.shortcuts import redirect, render, get_object_or_404
from django.db import transaction
from django.db.models import Sum, Q, Max, Count
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator

from .models import (
    Account, AccountProfile, Wallet,
    Category, Product, ProductImage,
    Cart, CartItem,
    Order, OrderItem
)


# =========================================================
# Helpers (Hàm dùng chung)
# =========================================================
def get_logged_in_account(request):
    """
    Lấy account đang đăng nhập từ session.
    Trả về None nếu chưa đăng nhập.
    """
    account_id = request.session.get("account_id")
    if not account_id:
        return None

    # Có thể dùng select_related nếu bạn đã khai báo OneToOne / FK đúng tên.
    return Account.objects.filter(id=account_id).first()


def build_common_ctx(account):
    """
    Context chung cho header: account, balance, total_cart_item
    - balance: lấy từ wallet (nếu có)
    - total_cart_item: số dòng CartItem (distinct items) trong giỏ (nếu có cart)
    """
    if not account:
        return {"account": None, "balance": 0, "total_cart_item": 0}

    # Wallet (OneToOne) có thể raise RelatedObjectDoesNotExist -> dùng try cho chắc
    try:
        balance = account.wallet.balance
    except Exception:
        balance = Decimal("0")

    # Cart (OneToOne) tương tự
    try:
        total_cart_item = CartItem.objects.filter(cart=account.cart).count()
    except Exception:
        total_cart_item = 0

    return {"account": account, "balance": balance, "total_cart_item": total_cart_item}


def _recalc_cart_quantity(cart):
    """
    Cập nhật cart.quantity = tổng số lượng (sum quantity) của các CartItem.
    """
    cart.quantity = CartItem.objects.filter(cart=cart).aggregate(s=Sum("quantity"))["s"] or 0
    cart.save(update_fields=["quantity"])


def _to_decimal(val, default="0"):
    """
    Parse Decimal an toàn (tránh crash khi input bậy).
    """
    try:
        return Decimal(str(val).strip())
    except Exception:
        return Decimal(default)


def _to_int(val, default=0):
    """
    Parse int an toàn.
    """
    try:
        return int(val)
    except Exception:
        return default


def _to_date(val, default_date=date(2025, 1, 1)):
    """
    Parse date từ string dạng YYYY-MM-DD.
    - Nếu parse fail -> dùng default_date.
    """
    try:
        if isinstance(val, date):
            return val
        s = str(val).strip()
        if not s:
            return default_date
        return date.fromisoformat(s)
    except Exception:
        return default_date


def _admin_required(request):
    """
    Check admin:
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


def _redirect_back(request, fallback_url_name):
    """
    Redirect về trang trước (HTTP_REFERER) nếu có,
    nếu không có -> redirect về fallback_url_name.
    """
    return redirect(request.META.get("HTTP_REFERER") or fallback_url_name)


# =========================================================
# Admin - Categories
# =========================================================
def admin_categories(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    q = (request.GET.get("q") or request.GET.get("keyword") or "").strip()

    qs = Category.objects.all()

    # ✅ Đếm số sản phẩm trong danh mục (product_count)
    # Tìm accessor của Product -> Category
    accessor = None
    for rel in Category._meta.related_objects:
        if rel.related_model == Product:
            accessor = rel.get_accessor_name()  # ví dụ: "product_set" hoặc "products" ...
            break

    if accessor:
        try:
            qs = qs.annotate(product_count=Count(accessor))
        except Exception:
            pass  # annotate fail thì thôi, vẫn list bình thường

    if q:
        qs = qs.filter(category_name__icontains=q)

    qs = qs.order_by("-category_id")

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    ctx = build_common_ctx(account)
    ctx.update({"page_obj": page_obj, "q": q})
    return render(request, "dashboard/admin_categories.html", ctx)


def admin_category_create(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    if request.method == "GET":
        ctx = build_common_ctx(account)
        return render(request, "dashboard/admin_category_create.html", ctx)

    name = (request.POST.get("category_name") or "").strip()

    ctx = build_common_ctx(account)

    if not name:
        ctx["error_message"] = "Vui lòng nhập tên danh mục."
        return render(request, "dashboard/admin_category_create.html", ctx)

    if Category.objects.filter(category_name__iexact=name).exists():
        ctx["error_message"] = "Danh mục này đã tồn tại."
        return render(request, "dashboard/admin_category_create.html", ctx)

    # quantity bạn đang dùng để sort ở dashboard (nav_categories), giữ nguyên
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
    ctx = build_common_ctx(account)
    ctx.update({"c": c})

    if not name:
        ctx["error_message"] = "Tên danh mục không được để trống."
        return render(request, "dashboard/admin_category_edit.html", ctx)

    if Category.objects.filter(category_name__iexact=name).exclude(category_id=c.category_id).exists():
        ctx["error_message"] = "Tên danh mục đã tồn tại."
        return render(request, "dashboard/admin_category_edit.html", ctx)

    c.category_name = name
    c.save(update_fields=["category_name"])
    return redirect("admin_categories")


@require_POST
def admin_category_delete(request, category_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    c = get_object_or_404(Category, category_id=category_id)

    # ✅ Chặn xóa nếu có sản phẩm
    if Product.objects.filter(category=c).exists():
        return redirect("admin_categories")

    c.delete()
    return redirect("admin_categories")


# =========================================================
# Dashboard / Home
# =========================================================
def dashboard(request):
    account = get_logged_in_account(request)
    ctx = build_common_ctx(account)

    q = (request.GET.get("q") or "").strip()
    cat = (request.GET.get("cat") or "").strip()
    page = request.GET.get("page") or 1

    categories = Category.objects.all().order_by("category_name")
    nav_categories = Category.objects.all().order_by("-quantity", "category_name")[:7]

    active_cat = int(cat) if cat.isdigit() else None

    qs = Product.objects.select_related("category").all().order_by("-product_id")

    if active_cat:
        qs = qs.filter(category_id=active_cat)

    if q:
        qs = qs.filter(
            Q(product_name__icontains=q)
            | Q(description__icontains=q)
            | Q(category__category_name__icontains=q)
        )

    page_obj = None

    # ===== HOME: không search và không lọc danh mục -> lấy 8 bán chạy =====
    if not active_cat and not q:
        top_ids = (
            OrderItem.objects
            .filter(order__status="PAID")
            .values("product_id")
            .annotate(sold=Sum("quantity"))
            .order_by("-sold")[:8]
        )
        top_ids = [x["product_id"] for x in top_ids if x["product_id"]]

        products_map = {p.product_id: p for p in qs.filter(product_id__in=top_ids)}
        products = [products_map[i] for i in top_ids if i in products_map]
        search_count = len(products)

    # ===== CATEGORY/SEARCH: phân trang 9 sp =====
    else:
        search_count = qs.count()
        paginator = Paginator(qs, 9)
        page_obj = paginator.get_page(page)
        products = page_obj.object_list

    ctx.update({
        "categories": categories,
        "nav_categories": nav_categories,
        "active_cat": active_cat,
        "products": products,
        "q": q,
        "search_count": search_count,
        "page_obj": page_obj,
    })
    return render(request, "dashboard/dashboard.html", ctx)


# =========================================================
# Admin page (tabs) - (bạn đang dùng như 1 dashboard admin)
# =========================================================
def to_admin_page(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    categories = Category.objects.all().order_by("category_name")
    products = Product.objects.select_related("category").order_by("-product_id")
    orders = Order.objects.select_related("account").order_by("-created_at")[:10]

    # NOTE: bạn đã có admin_product_create riêng,
    # nhưng bạn vẫn cho tạo nhanh ngay ở tab admin_page (giữ nguyên).
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


# =========================================================
# Cart (DB)
# =========================================================
def to_view_cart(request):
    """
    Trang giỏ hàng (GET).
    """
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


@require_POST
def add_to_cart(request, product_id):
    """
    Thêm 1 sản phẩm vào giỏ (POST).
    """
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    product = get_object_or_404(Product, product_id=product_id)
    cart, _ = Cart.objects.get_or_create(account=account, defaults={"quantity": 0})

    item = CartItem.objects.filter(cart=cart, product=product).first()
    if item:
        item.quantity += 1
        item.save(update_fields=["quantity"])
    else:
        CartItem.objects.create(cart=cart, product=product, quantity=1)

    _recalc_cart_quantity(cart)

    # redirect về trang trước cho UX tốt hơn
    return _redirect_back(request, "to_view_cart")


@require_POST
def cart_inc(request, product_id):
    """
    Tăng số lượng (POST). Dùng lại logic add_to_cart.
    """
    return add_to_cart(request, product_id)


@require_POST
def cart_dec(request, product_id):
    """
    Giảm số lượng (POST). Nếu <=0 thì xóa dòng đó.
    """
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
            item.save(update_fields=["quantity"])

    _recalc_cart_quantity(cart)
    return _redirect_back(request, "to_view_cart")


@require_POST
def cart_remove(request, product_id):
    """
    Xóa 1 sản phẩm khỏi giỏ (POST).
    """
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    cart = get_object_or_404(Cart, account=account)
    CartItem.objects.filter(cart=cart, product_id=product_id).delete()

    _recalc_cart_quantity(cart)
    return _redirect_back(request, "to_view_cart")


# =========================================================
# Auth
# =========================================================
def to_login_page(request):
    """
    Login (GET: render form, POST: check).
    NOTE: bạn đang dùng password plain text (demo).
    """
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
    """
    Register (GET/POST).
    Tạo đủ Account + Profile + Cart + Wallet.
    """
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

        with transaction.atomic():
            account = Account.objects.create(username=username, password=password)

            AccountProfile.objects.create(
                account=account,
                full_name="Chưa có",
                date_of_birth=date(2025, 1, 1),
                email=f"{username}@gmail.com",
                phone_number="0123456789"
            )

            Cart.objects.create(account=account, quantity=0)
            Wallet.objects.create(account=account, balance=Decimal("0"))

        return render(request, "dashboard/register_page.html", {
            "success_message": "Đăng kí thành công. Vui lòng đăng nhập."
        })

    return render(request, "dashboard/register_page.html")


def logout(request):
    request.session.flush()
    return redirect("dashboard")


# =========================================================
# Checkout / Orders (User)
# =========================================================
def checkout(request):
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    cart = get_object_or_404(Cart, account=account)
    cart_items = CartItem.objects.filter(cart=cart).select_related("product", "product__category")

    total = Decimal("0")
    for item in cart_items:
        total += (item.product.price * item.quantity)

    def _render(msg=None, balance_override=None):
        ctx = build_common_ctx(account)
        ctx.update({
            "cart_items": cart_items,
            "cart_total": total,
            "receiver_name": (request.POST.get("receiver_name") or "").strip(),
            "receiver_phone": (request.POST.get("receiver_phone") or "").strip(),
            "receiver_address": (request.POST.get("receiver_address") or "").strip(),
        })
        if msg:
            ctx["error_message"] = msg
        if balance_override is not None:
            ctx["balance"] = balance_override
        return render(request, "dashboard/checkout.html", ctx)

    if request.method == "GET":
        # GET: render form trống
        return _render()

    # POST: validate
    receiver_name = (request.POST.get("receiver_name") or "").strip()
    receiver_phone = (request.POST.get("receiver_phone") or "").strip()
    receiver_address = (request.POST.get("receiver_address") or "").strip()

    if total <= 0:
        return _render("Giỏ hàng đang trống.")
    if not receiver_name or not receiver_phone or not receiver_address:
        return _render("Vui lòng nhập đủ Họ tên, SĐT và Địa chỉ.")

    # Atomic để trừ ví + tạo đơn + tạo order items + clear cart
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(account=account)
        if wallet.balance < total:
            return _render("Số dư ví không đủ để thanh toán.", balance_override=wallet.balance)

        wallet.balance = wallet.balance - total
        wallet.save(update_fields=["balance"])

        order = Order.objects.create(
            account=account,
            total_amount=total,
            status="PAID",
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            receiver_address=receiver_address
        )

        # tạo OrderItem từ CartItem
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
        cart.save(update_fields=["quantity"])

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

    # order.items: related_name (bạn đang dùng)
    items = list(order.items.all())

    grand_total = Decimal("0")
    for it in items:
        it.line_total = it.unit_price * it.quantity
        grand_total += it.line_total

    ctx = build_common_ctx(account)
    ctx.update({"order": order, "items": items, "grand_total": grand_total})
    return render(request, "dashboard/order_detail.html", ctx)


# =========================================================
# Wallet
# =========================================================
def wallet_topup(request):
    """
    Nạp ví demo:
    - GET: hiển thị form
    - POST: cộng tiền (atomic + lock row wallet)
    """
    account = get_logged_in_account(request)
    if not account:
        return redirect("to_login_page")

    # đảm bảo luôn có wallet
    Wallet.objects.get_or_create(account=account, defaults={"balance": Decimal("0")})

    if request.method == "POST":
        amount = _to_decimal(request.POST.get("amount"), default="0")

        ctx = build_common_ctx(account)

        if amount <= 0:
            ctx["error_message"] = "Số tiền phải lớn hơn 0."
            return render(request, "dashboard/wallet_topup.html", ctx)

        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(account=account)
            wallet.balance = wallet.balance + amount
            wallet.save(update_fields=["balance"])

        return redirect("dashboard")

    ctx = build_common_ctx(account)
    return render(request, "dashboard/wallet_topup.html", ctx)


# =========================================================
# Product Detail (User)
# =========================================================
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

    # gallery (ProductImage related_name="gallery" bạn đang dùng)
    gallery = p.gallery.all().order_by("sort_order", "id")

    ctx.update({"p": p, "related": related, "gallery": gallery})
    return render(request, "dashboard/product_detail.html", ctx)


# =========================================================
# Admin Orders
# =========================================================
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
        order.save(update_fields=["status"])

    return redirect("admin_order_detail", order_id=order.order_id)


# =========================================================
# Admin Products (List/Create/Edit/Delete)
# =========================================================
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
    page_obj = paginator.get_page(request.GET.get("page"))

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


@require_POST
def admin_product_delete(request, product_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    p = get_object_or_404(Product, product_id=product_id)
    p.delete()
    return redirect("admin_products")


# =========================================================
# Admin Users
# =========================================================
def admin_users(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    q = (request.GET.get("q") or "").strip()

    qs = Account.objects.all().order_by("-id")
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(accountprofile__full_name__icontains=q)
            | Q(accountprofile__email__icontains=q)
            | Q(accountprofile__phone_number__icontains=q)
        )

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    ctx = build_common_ctx(account)
    ctx.update({"page_obj": page_obj, "q": q})
    return render(request, "dashboard/admin_users.html", ctx)


def admin_user_create(request):
    account, resp = _admin_required(request)
    if resp:
        return resp

    ctx = build_common_ctx(account)

    if request.method == "GET":
        return render(request, "dashboard/admin_user_create.html", ctx)

    username = (request.POST.get("username") or "").strip()
    password = (request.POST.get("password") or "").strip()
    role = (request.POST.get("role") or "USER").strip().upper()
    status = (request.POST.get("status") or "normal").strip()

    full_name = (request.POST.get("full_name") or "").strip() or "Chưa có"
    dob = _to_date(request.POST.get("date_of_birth") or "2025-01-01")
    email = (request.POST.get("email") or "").strip()
    phone = (request.POST.get("phone_number") or "").strip()
    balance = _to_decimal(request.POST.get("balance") or "0")

    if not username or not password:
        ctx["error_message"] = "Vui lòng nhập Username và Password."
        return render(request, "dashboard/admin_user_create.html", ctx)

    if role not in {"ADMIN", "USER"}:
        role = "USER"

    if Account.objects.filter(username=username).exists():
        ctx["error_message"] = "Username đã tồn tại."
        return render(request, "dashboard/admin_user_create.html", ctx)

    if email and AccountProfile.objects.filter(email=email).exists():
        ctx["error_message"] = "Email đã tồn tại."
        return render(request, "dashboard/admin_user_create.html", ctx)

    with transaction.atomic():
        u = Account.objects.create(username=username, password=password, role=role, status=status)

        AccountProfile.objects.create(
            account=u,
            full_name=full_name,
            date_of_birth=dob,
            email=(email or f"{username}@gmail.com"),
            phone_number=(phone or "0123456789"),
        )

        Cart.objects.create(account=u, quantity=0)
        Wallet.objects.create(account=u, balance=balance)

    return redirect("admin_users")


def admin_user_edit(request, user_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    u = get_object_or_404(Account, id=user_id)

    # đảm bảo luôn có profile + wallet + cart
    profile, _ = AccountProfile.objects.get_or_create(
        account=u,
        defaults={
            "full_name": "Chưa có",
            "date_of_birth": date(2025, 1, 1),
            "email": f"{u.username}@gmail.com",
            "phone_number": "0123456789",
        }
    )
    wallet, _ = Wallet.objects.get_or_create(account=u, defaults={"balance": Decimal("0")})
    Cart.objects.get_or_create(account=u, defaults={"quantity": 0})

    ctx = build_common_ctx(account)
    ctx.update({"u": u, "p": profile, "w": wallet})

    if request.method == "GET":
        return render(request, "dashboard/admin_user_edit.html", ctx)

    username = (request.POST.get("username") or "").strip()
    password = (request.POST.get("password") or "").strip()
    role = (request.POST.get("role") or "USER").strip().upper()
    status = (request.POST.get("status") or "normal").strip()

    full_name = (request.POST.get("full_name") or "").strip()
    dob = _to_date(request.POST.get("date_of_birth") or "", default_date=profile.date_of_birth or date(2025, 1, 1))
    email = (request.POST.get("email") or "").strip()
    phone = (request.POST.get("phone_number") or "").strip()
    balance = _to_decimal(request.POST.get("balance") or str(wallet.balance))

    if not username:
        ctx["error_message"] = "Username không được để trống."
        return render(request, "dashboard/admin_user_edit.html", ctx)

    if role not in {"ADMIN", "USER"}:
        role = "USER"

    if Account.objects.filter(username=username).exclude(id=u.id).exists():
        ctx["error_message"] = "Username đã tồn tại."
        return render(request, "dashboard/admin_user_edit.html", ctx)

    if email and AccountProfile.objects.filter(email=email).exclude(id=profile.id).exists():
        ctx["error_message"] = "Email đã tồn tại."
        return render(request, "dashboard/admin_user_edit.html", ctx)

    with transaction.atomic():
        u.username = username
        u.role = role
        u.status = status
        if password:
            u.password = password  # demo plain text
        u.save()

        profile.full_name = full_name or profile.full_name
        profile.date_of_birth = dob
        profile.email = email or profile.email
        profile.phone_number = phone or profile.phone_number
        profile.save()

        wallet.balance = balance
        wallet.save(update_fields=["balance"])

    return redirect("admin_users")


@require_POST
def admin_user_toggle(request, user_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    u = get_object_or_404(Account, id=user_id)

    # không tự khóa chính mình
    if u.id == account.id:
        return redirect("admin_users")

    u.status = "locked" if (u.status == "normal") else "normal"
    u.save(update_fields=["status"])
    return redirect("admin_users")


@require_POST
def admin_user_delete(request, user_id):
    account, resp = _admin_required(request)
    if resp:
        return resp

    u = get_object_or_404(Account, id=user_id)

    # không tự xóa chính mình
    if u.id == account.id:
        return redirect("admin_users")

    # nếu user có đơn -> KHÓA thay vì xóa để tránh bay Order
    if Order.objects.filter(account=u).exists():
        u.status = "locked"
        u.save(update_fields=["status"])
        return redirect("admin_users")

    u.delete()
    return redirect("admin_users")
