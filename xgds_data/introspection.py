# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from taggit.managers import TaggableManager

from xgds_data import settings

def modelFields(model):
    """
    Retrieve the fields associated with the given model
    """
    return model._meta.fields + model._meta.many_to_many


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


def resolveField(model, fieldName):
    """
    Retrieve the field corresponding to the the name, if any
    """
    for f in modelFields(model):
        if (fieldName == f.name):
            return f

    return None

def maskField(model, field):
    """
    Should we omit this field from search and display?
    """
    return (field.name in settings.XGDS_DATA_MASKED_FIELD) or isinstance(field,TaggableManager)


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


