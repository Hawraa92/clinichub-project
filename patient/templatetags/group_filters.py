from django import template

register = template.Library()

@register.filter
def has_group(user, group_name):
    """
    Returns True if the given user belongs to group_name.
    Usage in template: {% if request.user|has_group:"Doctors" %} … {% endif %}
    """
    return user.groups.filter(name=group_name).exists()
