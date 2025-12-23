from django import template
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

register = template.Library()

@register.filter
def vnd(value):
    """975000.00 -> 975.000 đ"""
    if value is None or value == "":
        return "0 đ"
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value

    # Làm tròn 0 chữ số thập phân (kiểu thông dụng)
    n = n.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # Đổi sang format kiểu 1.234.567
    s = f"{n:,}".replace(",", ".")
    return f"{s} đ"
