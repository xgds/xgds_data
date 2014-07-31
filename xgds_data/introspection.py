# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

try:
    from taggit.managers import TaggableManager
except:
    pass

from django.db.models import get_app
from django.db.models import fields
from xgds_data import settings
from xgds_data.models import VirtualField

def settingsForModel(settng, model):
    """
    Does the setting list this field?
    """
    mysettings = []
    for amodel in model.__mro__:
        try:
            mysettings = mysettings + settng.get(amodel._meta.app_label).get(amodel._meta.object_name)
        except:
            pass
        
    return mysettings


def modelFields(model):
    """
    Retrieve the fields associated with the given model
    """
    fields = model._meta.fields + model._meta.many_to_many + model._meta.virtual_fields
    try:
        for throughFieldName, relName, relVerboseName in settingsForModel(settings.XGDS_DATA_EXPAND_RELATED, model):
            fields = fields + [ VirtualField(throughFieldName,relName, relVerboseName) ]
    except:
        pass

    return fields


def isAbstract(model):
    """
    Check if model is abstract. Might be a better way to do this, but I didn't find it.
    """
    return model._meta.abstract


def pk(model):
    """
    return the primary key
    """
    return model._meta.pk


def resolveModel(moduleName, modelName):
    """
    Return the model with this name
    """
    modelmodule = get_app(moduleName)

    return getattr(modelmodule, modelName)


def resolveField(model, fieldName):
    """
    Retrieve the field corresponding to the the name, if any
    """
    for f in modelFields(model):
        if (fieldName == f.name):
            return f

    return None


def maskField(field):
    """
    Should we omit this field from search and display?
    """
    try:
        if isinstance(field,TaggableManager):
            return True
    except:
        pass
    
    try:
        return field.name in settingsForModel(settings.XGDS_DATA_MASKED_FIELDS, field.model)
    except:
        return False


def isOrdinalOveridden(model, field):
    """
    Is this a field that looks ordinal, but isn't really?
    """
    try:
        return field.name in settingsForModel(settings.XGDS_DATA_NONORDINAL_FIELDS, model)
    except:
        print('Error on',field)
        return False

def ordinalField(model, field):
    """
    Does this field support ranges?
    """
    if isinstance(field, (fields.DateTimeField,
                          fields.DecimalField,
                           fields.FloatField,
                           fields.IntegerField,
                           fields.PositiveIntegerField)):
        return not isOrdinalOveridden(model,field)
    else:
        return False


def concreteDescendents(model):
    """
    Get non-abstract descendants of this class. Does not check subclasses on concrete descendants.
    """
    if isAbstract(model):
        submodels = []
        for sub in model.__subclasses__():
            submodels = submodels + concreteDescendents(sub)
        return submodels
    else:
        return [model]


def concrete_model(model):
    """
    Get the concrete model
    """
    return model._meta.concrete_model


