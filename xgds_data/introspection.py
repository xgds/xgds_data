# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

def modelFields(model):
    """
    Retrieve the fields associated with the given model
    """
    return  model._meta.fields + model._meta.many_to_many

def resolveField(model, fieldName):
    """
    Retrieve the field corresponding to the the name, if any
    """
    for f in modelFields(model):
        if (fieldName == f.name):
            return f
    
    return None