#__BEGIN_LICENSE__
# Copyright (c) 2015, United States Government, as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All rights reserved.
#
# The xGDS platform is licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0.
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#__END_LICENSE__

try:
    from taggit.managers import TaggableManager
except (ImportError, RuntimeError):
    pass

from django.conf import settings
from django.db.models import fields
try:
    from django.apps import apps
except ImportError:
    from django.db.models import get_app

#from xgds_data.models import VirtualIncludedField
import xgds_data.models


def settingsForModel(settng, model):
    """
    Does the setting list this field?
    """
    mysettings = []
    for amodel in model.__mro__:
        try:
            mysettings = mysettings + settng.get(amodel._meta.app_label).get(amodel._meta.object_name, [])
        except (AttributeError, KeyError):
            pass

    return mysettings


def accessorDict(model):
    """
    returns a dict of accessor, base relation parts that can be used on this model
    """
    ad = dict([(x.name, x) for x in model._meta.fields])
    ad.update(dict([(x.name, x) for x in model._meta.many_to_many]))
    ## do we need virtual_fields? Not sure what those are
    ad.update(dict([(x.get_accessor_name(), x) for x in model._meta.get_all_related_objects()]))
    ad.update(dict([(x.get_accessor_name(), x) for x in model._meta.get_all_related_many_to_many_objects()]))

    return ad


def modelFields(model):
    """
    Retrieve the fields associated with the given model
    """
    fields = model._meta.fields
    many_to_many = model._meta.many_to_many
    virtual_fields = model._meta.virtual_fields
    try:
        myfields = fields + many_to_many + virtual_fields
    except TypeError:
        ## fields, many_to_many are tuples in 1.9
        myfields = fields + many_to_many + tuple(virtual_fields)

    # nameToField = dict([(x.name,x) for x in myfields])
    fieldNames = [x.name for x in myfields]
    for x in dir(model):
        try:
            if isinstance(getattr(model, x), fields.related.ForeignRelatedObjectsDescriptor):
                fieldNames.append(x )
        except AttributeError:
            ## django may though AttributeError even for things listed by dir
            pass
    try:
        expands = settingsForModel(settings.XGDS_DATA_EXPAND_RELATED, model)
    except AttributeError as inst:
        expands = []

    for throughFieldName, relName, relVerboseName in expands:
        if (throughFieldName is not None) and (throughFieldName in fieldNames):
            myfields = myfields + (xgds_data.models.VirtualIncludedField(model, throughFieldName, relName, relVerboseName),)
        else:
            print("Error- VirtualField {0} on {1} references nonexistent field {2}".format(relVerboseName, modelName(model), throughFieldName))

    return myfields


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


def pkValue(instance):
    """
    return the primary key value
    """
    try:
        return instance.pk
    except AttributeError:
        pkval = getattr(instance,pk(instance).name)
        try:
            return pkval.pk
        except AttributeError:
            return pkval


def modelName(model):
    """
    return the short name of the model (or of the instance's model)
    """
    return concrete_model(model)._meta.object_name


def qualifiedModelName(model):
    """
    Return the long model name with the module included
    """
    return '.'.join([model.__module__,modelName(model)])


def moduleName(model):
    """
    return the short name of the module (or of the instance's module)
    """
    return model._meta.app_label


def verbose_name(model):
    """
    return the verbose name of the model
    """
    ## return model._meta.verbose_name_raw
    return model._meta.verbose_name.title()


def verbose_name_plural(model):
    """
    return the verbose name of the model
    """
    return model._meta.verbose_name_plural.title()


def db_table(model):
    """
    return the database table for this model
    """
    return model._meta.db_table


# def resolveModule(moduleName):
#     """
#     Return the module with this name
#     """
#     try:
#         return apps.get_app_config(moduleName).module
#     except NameError:
#         return get_app(moduleName)


def getModuleNames():
    try:
        return [x.name for x in apps.get_app_configs()]
    except NameError:
        return [app.__name__ for app in get_apps()]


def getModels(moduleName):
    try:
        return apps.get_app_config(moduleName).get_models()
    except NameError:
        return get_models(get_app(moduleName))


def resolveModel(moduleName, modelName):
    """
    Return the model with this name
    """
    try:
#        aconfig = apps.get_app_config(moduleName)
#
#        return aconfig.get_model(modelName)
        return apps.get_model(moduleName, modelName)
    except NameError:
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
        if isinstance(field, TaggableManager):
            return True
    except NameError:
        pass

    try:
        if field.name in settingsForModel(settings.XGDS_DATA_UNMASKED_FIELDS, field.model):
            return False
    except AttributeError:
        pass

    try:
        if field.name in settingsForModel(settings.XGDS_DATA_MASKED_FIELDS, field.model):
            return True
    except AttributeError:
        pass

    try:
        if field is pk(field.model):
            return True
    except AttributeError:
        pass

    if field.name.startswith("_") and not field.name.startswith("__"):
        return True

    return False


def isOrdinalOveridden(model, field):
    """
    Is this a field that looks ordinal, but isn't really?
    """
    try:
        return field.name in settingsForModel(settings.XGDS_DATA_NONORDINAL_FIELDS, model)
    except AttributeError:
        return False


def isNumeric(model, field):
    """
    Is this a number field? Some aren't handled, though
    """
    return (isinstance(field, (fields.AutoField,
                               fields.BigIntegerField,
                               fields.DecimalField,
                               fields.FloatField,
                               fields.IntegerField,
                               fields.PositiveIntegerField,
                               fields.PositiveSmallIntegerField,
                               fields.SmallIntegerField))
            and not isOrdinalOveridden(model, field))


def fieldModel(field):
    """
    Return the model that stores this field data
    """
    try:
        return fieldModel(field.targetFields()[0])
    except (IndexError, AttributeError):
        return field.model


def parentField(model,parent):
    """
    return the field that points to this parent
    """
    return model._meta.parents[parent]


## need to make this handle virtual field properly- probably pull out code from form and put in virtual field
def ordinalField(model, field):
    """
    Does this field support ranges?
    """
    if isOrdinalOveridden(model, field):
        return False
    elif isinstance(field, xgds_data.models.VirtualIncludedField):
        if len(field.targetFields()):
            for tmf in field.targetFields():
                if not ordinalField(tmf.model, tmf):
                    return False
            return True
        else:
            ## I think we missed it
            return False;
    elif isinstance(field, (fields.AutoField,
                            fields.DateTimeField,
                            fields.DateField,
                            fields.DecimalField,
                            fields.FloatField,
                            fields.IntegerField,
                            fields.PositiveIntegerField)):
        return True
    else:
        return False


def concreteDescendants(model):
    """
    Get non-abstract descendants of this class. Does not check subclasses on concrete descendants.
    """
    if isAbstract(model):
        submodels = []
        for sub in model.__subclasses__():
            submodels = submodels + concreteDescendants(sub)
        return submodels
    else:
        return [model]


def concrete_model(model):
    """
    Get the concrete model
    """
    return model._meta.concrete_model


def fullid(record):
    """An id that includes class info"""
    return '%s:%s:%s' % (moduleName(record),
                         modelName(record),
                         record.pk)
## getattr(record,pk(record).name))
