from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


# ── Custom Manager ───────────────────────────────────────────────
class CustomUserManager(BaseUserManager):
    """Email is the unique identifier instead of username."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", False)   # inactive until email verified
        extra_fields.pop("username", None)            # avoid duplicate kwarg
        user = self.model(email=email, username=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff",     True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active",    True)
        return self.create_user(email, password, **extra_fields)


# ── Custom User Model ────────────────────────────────────────────
class CustomUser(AbstractUser):
    """
    Replaces Django's default User.
    - Login is by email, not username.
    - Extra profile fields for a trading platform.
    """

    # Make email the primary identifier
    email = models.EmailField(unique=True)
    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]   # asked by createsuperuser

    # username kept (inherited) but we just mirror it from email —
    # required by some third-party packages, not shown to the user.

    # ── Profile ──────────────────────────────────────────────────
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional. E.164 format recommended, e.g. +48123456789",
    )
    date_of_birth = models.DateField(
        null=True, blank=True,
        help_text="Used for age verification on certain asset classes.",
    )
    avatar = models.ImageField(
        upload_to="avatars/",
        null=True, blank=True,
        help_text="Profile picture.",
    )

    # ── Account status ────────────────────────────────────────────
    email_verified = models.BooleanField(
        default=False,
        help_text="Set to True after the user clicks the verification link.",
    )

    # ── Trading preferences ───────────────────────────────────────
    class Currency(models.TextChoices):
        USD = "USD", "US Dollar"
        EUR = "EUR", "Euro"
        GBP = "GBP", "British Pound"
        PLN = "PLN", "Polish Złoty"

    default_currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.USD,
    )

    class RiskProfile(models.TextChoices):
        CONSERVATIVE = "conservative", "Conservative"
        MODERATE     = "moderate",     "Moderate"
        AGGRESSIVE   = "aggressive",   "Aggressive"

    risk_profile = models.CharField(
        max_length=20,
        choices=RiskProfile.choices,
        default=RiskProfile.MODERATE,
    )

    notifications_enabled = models.BooleanField(
        default=True,
        help_text="Receive price alerts and trade confirmations.",
    )

    # ── Demo account ──────────────────────────────────────────────
    demo_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=100000.00,
        help_text="Virtual demo balance in USD.",
    )
    disclaimer_accepted = models.BooleanField(
        default=False,
        help_text="User has accepted the demo account disclaimer.",
    )

    # ── Timestamps ────────────────────────────────────────────────
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

    class Meta:
        verbose_name        = "User"
        verbose_name_plural = "Users"
        ordering            = ["-created_at"]

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}>"

    @property
    def full_name(self):
        return self.get_full_name() or self.email

    def activate(self):
        """Called after successful email verification."""
        self.is_active      = True
        self.email_verified = True
        self.save(update_fields=["is_active", "email_verified"])


# ── Position ─────────────────────────────────────────────────────
class Position(models.Model):
    """A user's open holding in a single stock."""

    user          = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="positions"
    )
    symbol        = models.CharField(max_length=10)
    shares        = models.DecimalField(max_digits=14, decimal_places=6)
    avg_buy_price = models.DecimalField(max_digits=14, decimal_places=4)
    opened_at     = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "symbol")
        ordering        = ["-updated_at"]

    def __str__(self):
        return f"{self.user.email} — {self.symbol} × {self.shares}"

    @property
    def cost_basis(self):
        return float(self.shares) * float(self.avg_buy_price)