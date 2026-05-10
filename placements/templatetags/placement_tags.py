from django import template

register = template.Library()

@register.filter(name='split')
def split_filter(value, key):
    return value.split(key)

@register.filter(name='trim')
def trim_filter(value):
    return value.strip()