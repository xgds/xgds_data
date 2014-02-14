import re
from django import template
from django.conf import settings
from django.db.models.manager import Manager

integer_test = re.compile(r'^\d+$')
numeric_test = re.compile(r'^[\.\-Ee\d]+$')
register = template.Library()


# # http://stackoverflow.com/questions/844746/performing-a-getattr-style-lookup-in-a-django-template
def getattribute(value, arg):
    """Gets an attribute of an object dynamically from a string name"""

    if hasattr(value, str(arg)):
        v = getattr(value, arg)
    elif hasattr(value, 'has_key') and arg in value:
        v = value[arg]
    elif integer_test.match(str(arg)) and len(value) > int(arg):
        v = value[int(arg)]
    else:
        v = settings.TEMPLATE_STRING_IF_INVALID
    if (isinstance(v, Manager)):
        v = ' '.join([str(x) for x in v.all()])

    return v

register.filter('getattribute', getattribute)


def modulo(value, arg):
    """Computes value % arg"""

    return value % arg

register.filter('modulo', modulo)


def isNumeric(value):
    """tests to see if this is a number or not"""
    return numeric_test.match(str(value))

register.filter('isNumeric', isNumeric)


def divide(value, arg):
    """Computes value / arg"""

    return float(value) / float(arg)

register.filter('divide', divide)


def addfloat(value, arg):
    """Computes value + arg"""

    return float(value) + float(arg)

register.filter('addfloat', addfloat)


def dorange(value, arg):
    """access to range function"""
    return range(value, arg)

register.filter('range', dorange)
