import re
from django import template
from django.conf import settings
from django.db.models.manager import Manager

integer_test = re.compile("^\d+$")
numeric_test = re.compile("^[\.\-Ee\d]+$")
register = template.Library()

## http://stackoverflow.com/questions/844746/performing-a-getattr-style-lookup-in-a-django-template
def getattribute(value, arg):
    """Gets an attribute of an object dynamically from a string name"""
    
    if hasattr(value, str(arg)):
        v = getattr(value, arg)
    elif hasattr(value, 'has_key') and value.has_key(arg):
        v =  value[arg]
    elif integer_test.match(str(arg)) and len(value) > int(arg):
        v =  value[int(arg)]
    else:
        v =  settings.TEMPLATE_STRING_IF_INVALID
    if (isinstance(v,Manager)):
        v = ' '.join([str(x) for x in v.all()])
        
    return v

register.filter('getattribute', getattribute)

def modulo(value, arg):
    """Computes value % arg"""

    return value % arg

register.filter('modulo', modulo)

def isNumeric(value):
    """Computes value % arg"""
    return numeric_test.match(str(value))

register.filter('isNumeric', isNumeric)