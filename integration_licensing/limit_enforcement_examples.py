"""
Examples only. Copy the relevant calls into the services/views that create
users, branches and pharmacies.
"""

from licensing.services import LicenseLimitExceeded, assert_can_add


def before_creating_active_user():
    assert_can_add("max_users")
    # User.objects.create_user(...)


def before_creating_branch():
    assert_can_add("max_branches")
    # Branch.objects.create(...)


def before_creating_pharmacy():
    assert_can_add("max_pharmacies")
    # Pharmacy.objects.create(...)


# In a normal Django view, catch LicenseLimitExceeded and show its message:
#
# try:
#     assert_can_add("max_pharmacies")
# except LicenseLimitExceeded as exc:
#     messages.error(request, str(exc))
#     return redirect("...")
