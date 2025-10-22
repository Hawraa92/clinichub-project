from django.contrib import admin
from django.template.defaultfilters import filesizeformat
from .models import PatientArchive, ArchiveAttachment

class ArchiveAttachmentInline(admin.TabularInline):
    model = ArchiveAttachment
    extra = 1
    readonly_fields = ['uploaded_at', 'uploaded_by', 'file_size_display', 'image_tag']
    fields = ['file', 'description', 'uploaded_at', 'uploaded_by', 'file_size_display', 'image_tag']
    show_change_link = True

    def file_size_display(self, obj):
        return filesizeformat(obj.file.size)
    file_size_display.short_description = "Size"

    def image_tag(self, obj):
        return obj.image_tag()
    image_tag.allow_tags = True
    image_tag.short_description = "Preview"

@admin.register(PatientArchive)
class PatientArchiveAdmin(admin.ModelAdmin):
    list_display = [
        'patient', 'doctor', 'title', 'archive_type', 'is_critical', 'status',
        'created_at', 'created_by'
    ]
    list_filter = ['archive_type', 'is_critical', 'status', 'created_at']
    search_fields = ['title', 'notes', 'patient__full_name', 'doctor__user__full_name']
    readonly_fields = [
        'created_at', 'updated_at', 'created_by', 'updated_by'
    ]
    inlines = [ArchiveAttachmentInline]
    date_hierarchy = 'created_at'

@admin.register(ArchiveAttachment)
class ArchiveAttachmentAdmin(admin.ModelAdmin):
    list_display = [
        'short_file_name', 'archive', 'uploaded_at', 'uploaded_by', 'file_size_display'
    ]
    search_fields = ['file', 'description', 'archive__title']
    readonly_fields = ['uploaded_at', 'uploaded_by', 'file_size_display', 'image_tag']

    def short_file_name(self, obj):
        return obj.file.name.split('/')[-1]

    def file_size_display(self, obj):
        return filesizeformat(obj.file.size)

    def image_tag(self, obj):
        return obj.image_tag()
    image_tag.allow_tags = True
    image_tag.short_description = "Preview"
