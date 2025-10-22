# File: prescription/urls.py

from django.urls import path
from django.http import HttpResponseNotFound
from . import views

app_name = "prescription"

def _missing_view_factory(candidates):
    def _fallback(request, *args, **kwargs):
        return HttpResponseNotFound(
            "Missing view. Tried: " + ", ".join(candidates)
        )
    return _fallback

def pick(*names):
    """
    يحاول إرجاع أول فيو موجود (callable) من الأسماء المعطاة.
    إن لم يجد أي اسم، يرجّع فيو بديل يعرض رسالة خطأ لطيفة بدل ما يكسر المشروع.
    """
    for name in names:
        v = getattr(views, name, None)
        if callable(v):
            return v
    return _missing_view_factory(names)

urlpatterns = [
    # ➕ New Prescription — جرّب الأسماء التالية حسب الموجود عندك
    path("new/", pick("new_prescription", "prescription_create", "create_prescription"), name="new_prescription"),

    # 🗂️ قائمة الوصفات
    path("", pick("prescription_list", "list_prescriptions", "prescriptions", "index"), name="list"),

    # ➕ إنشاء وصفة لموعد محدد
    path("create/<int:appointment_id>/", pick("create_prescription", "prescription_create", "new_prescription"), name="create"),

    # 📄 تفاصيل الوصفة
    path("<int:pk>/", pick("prescription_detail", "detail", "show_prescription"), name="prescription_detail"),

    # ✏️ تعديل
    path("<int:pk>/edit/", pick("edit_prescription", "prescription_edit", "update_prescription"), name="edit"),

    # 🗑️ حذف
    path("<int:pk>/delete/", pick("delete_prescription", "prescription_delete", "remove_prescription"), name="delete"),

    # 📥 PDF
    path("<int:pk>/pdf/", pick("download_pdf_prescription", "prescription_pdf", "pdf"), name="download_pdf"),

    # 📤 واتساب
    path("<int:pk>/whatsapp/", pick("send_prescription_whatsapp", "prescription_whatsapp", "send_whatsapp"), name="send_whatsapp"),
]
