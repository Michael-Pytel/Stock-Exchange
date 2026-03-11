from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser

    list_display  = ("email", "first_name", "last_name", "is_active", "email_verified", "created_at")
    list_filter   = ("is_active", "email_verified", "risk_profile", "default_currency")
    search_fields = ("email", "first_name", "last_name")
    ordering      = ("-created_at",)

    # Override fieldsets to use email as primary field
    fieldsets = (
        (None,              {"fields": ("email", "password")}),
        ("Personal info",   {"fields": ("first_name", "last_name", "phone_number", "date_of_birth", "avatar")}),
        ("Trading prefs",   {"fields": ("default_currency", "risk_profile", "notifications_enabled")}),
        ("Status",          {"fields": ("is_active", "email_verified", "is_staff", "is_superuser")}),
        ("Permissions",     {"fields": ("groups", "user_permissions")}),
        ("Timestamps",      {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields":  ("email", "first_name", "last_name", "password1", "password2"),
        }),
    )