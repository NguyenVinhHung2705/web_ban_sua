from django.db import models

# Create your models here.
class Account(models.Model):
    username = models.CharField(max_length=20, unique=True)
    password = models.CharField(max_length=20)
    role = models.CharField(max_length=20, default='USER')  # e.g., 'admin', 'user'
    status = models.CharField(max_length=20, default='normal')  # locked or active

    def __str__(self):
        return self.username
    
class AccountProfile(models.Model):
    account = models.OneToOneField(Account, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=30)
    date_of_birth = models.DateField()
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=12)

    def __str__(self):
        return self.full_name

class Wallet(models.Model):
    wallet_id = models.AutoField(primary_key=True)
    account = models.OneToOneField(Account, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.account.username}'s Wallet"
    
class Category(models.Model):
    category_id = models.AutoField(primary_key=True)
    category_name = models.CharField(max_length=50, unique=True)
    quantity = models.IntegerField(default=0)  # để khỏi bắt nhập tay

    def __str__(self):
        return self.category_name
    
class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    product_name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    category = models.ForeignKey("Category", on_delete=models.SET_NULL, null=True, blank=True)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    description = models.TextField(blank=True, default="")

    # ✅ NEW: badges
    is_genuine = models.BooleanField(default=True)      # Chính hãng
    is_fast_ship = models.BooleanField(default=True)    # Giao nhanh

    # ✅ NEW: “3 ô gợi ý” (như ảnh)
    hint_text = models.CharField(max_length=255, blank=True, default="Uống ngon hơn khi lạnh")
    storage_short = models.CharField(max_length=255, blank=True, default="Nơi khô ráo, thoáng mát")
    return_policy = models.CharField(max_length=255, blank=True, default="7 ngày nếu lỗi")

    # ✅ NEW: Hướng dẫn bảo quản (gõ nhiều dòng, mỗi dòng 1 gạch đầu dòng)
    storage_guide = models.TextField(blank=True, default="Bảo quản nơi khô ráo và thoáng mát.\nĐóng kín sau khi mở.\nNgon hơn khi uống lạnh.")

    # ✅ NEW: Nutrition
    energy_kcal = models.IntegerField(default=0)  # 60
    protein_g = models.DecimalField(max_digits=6, decimal_places=1, default=0)  # 3.0
    fat_g = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    carb_g = models.DecimalField(max_digits=6, decimal_places=1, default=0)

    def __str__(self):
        return self.product_name


# ✅ NEW: Gallery ảnh (nhiều ảnh cho 1 product)
class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="gallery")
    image = models.ImageField(upload_to="products/gallery/")
    sort_order = models.IntegerField(default=0)

    def __str__(self):
        return f"Image of {self.product.product_name}"
    
class Cart(models.Model):
    cart_id = models.AutoField(primary_key=True)
    account = models.OneToOneField(Account, on_delete=models.CASCADE)
    quantity = models.IntegerField(default = 0)
    def __str__(self):
        return f"Cart {self.cart_id} for {self.account.username}"
    
class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()

    def __str__(self):
        return f"{self.quantity} of {self.product.product_name} in Cart {self.cart.cart_id}"


class Order(models.Model):
    order_id = models.AutoField(primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, default='PAID')

    receiver_name = models.CharField(max_length=80, default="", blank=True)
    receiver_phone = models.CharField(max_length=20, default="", blank=True)
    receiver_address = models.CharField(max_length=255, default="", blank=True)

    def __str__(self):
        return f"Order #{self.order_id} - {self.account.username}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)

    product_image_name = models.CharField(max_length=255, default="", blank=True)

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"

