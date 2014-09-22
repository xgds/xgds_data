import re
from django import template
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.manager import Manager
from django.db.models.fields.files import ImageField
from django.utils.safestring import mark_safe
from string import capwords

integer_test = re.compile(r'^\d+$')
numeric_test = re.compile(r'^[\.\-Ee\d]+$')
register = template.Library()

from django.db import models
from xgds_data.models import VirtualIncludedField


# http://stackoverflow.com/questions/844746/performing-a-getattr-style-lookup-in-a-django-template
def getattribute(value, arg):
    """Gets an attribute of an object dynamically from a string name"""
    if hasattr(value, str(arg)):
        v = getattr(value, arg)
    elif hasattr(value, 'has_key') and arg in value:
        v = value[arg]
    elif integer_test.match(str(arg)) and len(value) > int(arg):
        v = value[int(arg)]
    elif isinstance(arg, VirtualIncludedField):
        try:
            #throughInstance = arg.throughfield.__get__(value);
            throughInstance = getattr(value, arg.throughfield_name)
            includedFieldName = arg.name
            if throughInstance:
                v = getattr(throughInstance, includedFieldName)
            else:
                v = None
        except AttributeError as inst:
            ## print(inst)
            print('Error on ', value, arg)
            v = None
    elif isinstance(arg, models.Field):
        v = getattr(value, arg.name)
    else:
        v = settings.TEMPLATE_STRING_IF_INVALID
    if (isinstance(v, Manager)):
        v = ' '.join([str(x) for x in v.all()])
    return v

register.filter('getattribute', getattribute)


def display(field, value):
    """Returns html snippet appropriate for value and field"""
    if isinstance(field, ImageField):
        return mark_safe('<A HREF="' + field.storage.url(value) + '"><IMG SRC="' + field.storage.url(value) + '" WIDTH="100"></A>')
    elif isinstance(value, basestring):
        return value
    elif isinstance(value, User):
        return ', '.join([value.last_name, value.first_name])
    else:
        try:
            return ', '.join(value)
        except TypeError:
            return value

register.filter('display', display)


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


def verbose_name(field):
    """Get the verbose name, or make one up if undefined"""
    try:
        return field.verbose_name
    except:
        return capwords(re.sub( r"([A-Z])", r" \1", field.name))

register.filter('verbose_name', verbose_name)
