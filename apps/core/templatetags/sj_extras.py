"""Small presentation helpers for the SevaJobs templates."""

from __future__ import annotations

from django import template

register = template.Library()


@register.filter(name="split")
def split(value: str, separator: str = ","):
    """Split a string into a list — handy for static design data in templates."""
    if value is None:
        return []
    return [part.strip() for part in str(value).split(separator)]


@register.filter(name="pairs")
def pairs(value: str, item_sep: str = ";"):
    """
    Split ``"a|icon;b|icon"`` into ``[["a","icon"], ["b","icon"]]``.
    Lets templates carry small label/icon datasets without a view.
    """
    if not value:
        return []
    return [item.split("|") for item in str(value).split(item_sep)]


@register.filter(name="get_item")
def get_item(mapping, key):
    """Dictionary lookup by variable key inside a template."""
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter(name="status_class")
def status_class(value: str) -> str:
    """Map an application status to its CSS pill class suffix."""
    return f"status-{value}" if value else "status-applied"
