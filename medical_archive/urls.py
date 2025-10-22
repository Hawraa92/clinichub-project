from django.urls import path
from . import views

app_name = 'medical_archive'

urlpatterns = [
    # 📂 List all archives (عرض جميع الأرشيفات للمريض)
    path('', views.archive_list, name='archive_list'),

    # ➕ Create a new archive (إنشاء سجل أرشيف جديد)
    path('create/', views.create_archive, name='create_archive'),

    # 🔍 View archive detail and attachments (عرض تفاصيل الأرشيف والمرفقات)
    path('<int:archive_id>/', views.archive_detail, name='archive_detail'),

    # ✏️ Edit archive info (تعديل الأرشيف: العنوان، الملاحظات، إلخ)
    path('<int:archive_id>/edit/', views.edit_archive, name='edit_archive'),

    # 🗑️ Delete an archive (حذف الأرشيف والمرفقات)
    path('<int:archive_id>/delete/', views.delete_archive, name='delete_archive'),

    # 📨 Download single attachment (تنزيل مرفق واحد)
    path('attachment/<int:attachment_id>/download/', views.download_attachment, name='download_attachment'),
]
