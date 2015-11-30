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

from django import forms
from django.db import models
from django.utils.safestring import mark_safe
from django.db.models import fields
from django.forms.widgets import RadioSelect, TextInput
from django.contrib.contenttypes.generic import GenericForeignKey
from django.contrib.auth.models import User

from django.conf import settings
from xgds_data.models import VirtualIncludedField
from xgds_data.introspection import (modelFields, maskField, isOrdinalOveridden, isAbstract, pk, ordinalField, modelName)
from xgds_data.DataStatistics import tableSize, fieldSize
from xgds_data.utils import label
# pylint: disable=R0924


class QueryForm(forms.Form):
    query = forms.CharField(max_length=256, required=False,
                            widget=forms.TextInput(attrs={'size': 100}))
    mostRecentFirst = forms.BooleanField(label='Most recent first',
                                         required=False,
                                         initial=True)


class specialModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return label(obj)


def estimateFieldCount(field, itemCount, maxItemCount, maxFieldCount):
    """
    How many values occur for this field?
    """
    estCount = None
    try:
        estCount = tableSize(field.rel.to)
    except AttributeError:
        if (itemCount < maxItemCount):
            estCount = itemCount
        elif (itemCount < maxFieldCount):
            estCount = field.model.objects.values(field.name).order_by().distinct().count()

    return estCount


def specialWidget(mymodel, field, enumerableFields):
    """
    Determines the appropriate widget display if several could be applicable; otherwise returns None
    """
    widget = None
    if isinstance(field, (models.ForeignKey,models.ManyToManyField,models.OneToOneField)):
        if enumerableFields:
            if (field in enumerableFields):
                widget = 'pulldown'
        elif (not isAbstract(mymodel)) and (not isinstance(field, models.FileField)):
            try:
                maxpulldown = settings.XGDS_DATA_MAX_PULLDOWNABLE
            except AttributeError:
                maxpulldown = 100
            relatedCount = fieldSize(field, tableSize(mymodel), maxpulldown, 10 * maxpulldown)
            if (relatedCount is not None) and (relatedCount <= maxpulldown):
                widget = 'pulldown'
            else:
                widget = 'textbox'
    return widget


def operatorFormField(mymodel, field, widget):
    """
    Returns form field to choose an search operator for this model field
    """
    rangeOperators = (('IN~', 'IN~'),
                      ('IN', 'IN'),
                      ('NOT IN', 'NOT IN'))
    categoricalOperators = (('=', '='),
                            ('!=', '!='))
    textOperators = (('=', '='),
                     ('!=', '!='))
    if widget is 'pulldown':
        return forms.ChoiceField(choices=categoricalOperators,
                                 initial=categoricalOperators[0][0],
                                 required=True)
    elif widget is 'textbox':
        return forms.ChoiceField(choices=textOperators,
                                 initial=textOperators[0][0],
                                 required=True)
    elif ordinalField(mymodel, field):
        return forms.ChoiceField(choices=rangeOperators,
                                 initial=rangeOperators[0][0],
                                 required=True)
    elif isinstance(field, (models.AutoField, models.CharField, models.TextField)) or isOrdinalOveridden(mymodel, field):
        return forms.ChoiceField(choices=textOperators,
                                 initial=textOperators[0][0],
                                 required=True)
    elif isinstance(field, (models.BooleanField, models.NullBooleanField)):
        return forms.ChoiceField(choices=categoricalOperators,
                                 initial=categoricalOperators[0][0],
                                 required=True)
    else:
        return None


def valueFormField(mymodel, field, widget, allowMultiple=True, label=None):
    """
    Returns form field to provide a value appropriate for this model field
    """
    if isinstance(field, (models.CharField, models.TextField)) or isOrdinalOveridden(mymodel, field):
        return forms.CharField(required=False,label=label)
    elif isinstance(field, models.DateTimeField):
        return forms.DateTimeField(required=False,label=label)
    elif isinstance(field, (models.DecimalField, models.FloatField)):
        return forms.FloatField(required=False,label=label)
    elif isinstance(field, models.PositiveIntegerField):
        return forms.IntegerField(min_value=1, required=False,label=label)
    elif isinstance(field, (models.AutoField, models.IntegerField)):
        return forms.IntegerField(required=False,label=label)
    elif isinstance(field, (models.BooleanField, models.NullBooleanField)):
        return forms.ChoiceField(choices=(("", '<Any>'),
                                       (True, True),
                                       (False, False)),
                                 required=False,
                                 label=label)   
    elif isinstance(field, (models.ForeignKey,models.ManyToManyField,models.OneToOneField)):
        if widget is 'pulldown':
            # can't use as queryset arg because it needs a queryset, not a list
            # foreigners = sorted(field.related.parent_model.objects.all(), key=lambda x: unicode(x))
            qset = field.related.parent_model.objects.all()
            if (field.related.parent_model == User):
                qset = qset.order_by('last_name')
            if isinstance(field, models.ManyToManyField) and allowMultiple:
                return forms.ModelMultipleChoiceField(queryset=qset,
                                                      required=False,
                                                      label=label)
            else:
                return specialModelChoiceField(queryset=qset,
                                               # initial=qset,
                                               # order_by('name'),
                                               empty_label="<Any>",
                                               required=False,
                                               label=label)
        elif widget is 'textbox':
            qset = field.related.parent_model.objects.all()
            try:
                to_field = [x for x in modelFields(field.rel.to) if x.name == 'name'][0]
            except IndexError:
                to_field = pk(field.rel.to)
            return forms.ModelChoiceField(queryset=qset,
                                          to_field_name=to_field.name,
                                          initial=None,
                                          widget=TextInput,
                                          required=False,
                                          label=label)
            # self.fields[field.name] = forms.CharField(required=False)
    else:
        return None


def fieldNameBase(field,name):
    """
    Get the form field name
    """
    if isinstance(field, VirtualIncludedField):
        return name
    else:
        return name

def searchFormFields(mymodel, field, enumerableFields):
    """
    Returns a dict of Form fields to add to a search form, based on the model field
    """
    formfields = {}
    if maskField(field):
        pass  # nothing
    elif isinstance(field, VirtualIncludedField):
        tmfs = field.targetFields()
        if len(tmfs):
            #  need to assume all are the same, so just use the first one
            #print(searchFormFields(tmfs[0].model, tmfs[0], enumerableFields))
            vfields = dict()
            for name,ff in searchFormFields(tmfs[0].model, tmfs[0], enumerableFields).iteritems():
                vfields[fieldNameBase(field,name)] = ff
            formfields.update(vfields)
    else:
        widget = specialWidget(mymodel, field, enumerableFields)
        opField = operatorFormField(mymodel, field, widget)
        if opField is None:
            #  This must be class that we have missed of haven't gotten around to supporting/ignoring
            longname = '.'.join([field.__class__.__module__,
                                 field.__class__.__name__])
            print("SearchForm forms doesn't deal with %s yet" % longname)
        else:
            ##fieldnamebase = modelName(mymodel)+'.'+field.name
            fieldnamebase = fieldNameBase(field,field.name)
            formfields[fieldnamebase + '_operator'] = opField
            if ordinalField(mymodel, field):
                formfields[fieldnamebase + '_lo'] = valueFormField(mymodel, field, widget)
                formfields[fieldnamebase + '_hi'] = valueFormField(mymodel, field, widget)
            else:
                formfields[fieldnamebase] = valueFormField(mymodel, field, widget, allowMultiple=False)

    return formfields


class SearchForm(forms.Form):
    """
    Dynamically creates a form to search the given class
    """
    def __init__(self, mymodel, *args, **kwargs):
        enumerableFields = kwargs.pop('enumerableFields', None)
        forms.Form.__init__(self, *args, **kwargs)
        self.model = mymodel

        for field in modelFields(mymodel):
            self.fields.update(searchFormFields(mymodel, field, enumerableFields))

    def as_table(self):
        output = []

        for mfield in modelFields(self.model):
            # self.model._meta.fields:
            # n = mfield.name
            fieldname = fieldNameBase(mfield,mfield.name)
            # if (isinstance(mfield, VirtualIncludedField)):
            #    fieldname = mfield.compound_name()
            if (fieldname in self.fields or
                ((fieldname + '_lo') in self.fields and
                 (fieldname + '_hi') in self.fields)):
                ofieldname = fieldname + '_operator'
                ofield = forms.forms.BoundField(self, self.fields[ofieldname], ofieldname)
                if ordinalField(self.model, mfield):
                    loname, hiname = fieldname + '_lo', fieldname + '_hi'
                    fieldlo = forms.forms.BoundField(self, self.fields[loname], loname)
                    fieldhi = forms.forms.BoundField(self, self.fields[hiname], hiname)
                    row = (u'<tr><td style="text-align:right;"><label for="%(fieldid)s">%(label)s</label></td><td>%(ofield)s</td>' %
                           {'label': unicode(mfield.verbose_name),
                            'ofield': unicode(ofield.as_hidden()),
                            'fieldid': unicode(fieldlo.auto_id)
                            })
                    row = (row + u'<td>%(fieldlo)s</td><td><label for="%(fieldhi_id)s">up to</label></td><td>%(fieldhi)s</td>' %
                           {'fieldlo': unicode(fieldlo),
                            'fieldhi': unicode(fieldhi),
                            'fieldhi_id': unicode(fieldhi.auto_id)})
                else:
                    row = (u'<tr><td style="text-align:right;"><label for="%(fieldid)s">%(label)s</label></td><td>%(ofield)s</td>' %
                           {'label': unicode(mfield.verbose_name),
                            'ofield': unicode(ofield.as_hidden()),
                            'fieldid': unicode(ofield.auto_id[:-9])
                            })
                    try:
                        bfield = forms.forms.BoundField(self, self.fields[fieldname],
                                                        fieldname)
                        row = (row + u'<td colspan=3>%(field)s</td>' %
                               {'field': unicode(bfield)})
                    except AttributeError:
                        row = None ### HERE
                if row is not None:
                    row = row + u'</tr>'
                    output.append(row)

        return mark_safe(u'\n'.join(output))

    def as_expert_table(self):
        output = []

        for mfield in modelFields(self.model):
            n = mfield.name
            if (n in self.fields or
                ((n + '_lo') in self.fields and
                 (n + '_hi') in self.fields)):
                ofieldname = n + '_operator'
                ofield = forms.forms.BoundField(self, self.fields[ofieldname], ofieldname)

                if ordinalField(self.model, mfield):
                    loname, hiname = mfield.name + '_lo', mfield.name + '_hi'
                    fieldlo = forms.forms.BoundField(self, self.fields[loname], loname)
                    fieldhi = forms.forms.BoundField(self, self.fields[hiname], hiname)
                    row = (u'<tr><td style="text-align:right;"><label for="%(fieldid)s">%(label)s</label></td><td>%(ofield)s</td>' %
                           {'label': unicode(mfield.verbose_name),
                            'ofield': unicode(ofield),
                            'fieldid': unicode(fieldlo.auto_id)})
                    row = (row + u'<td>%(fieldlo)s</td><td><label for="%(fieldhi_id)s">up to</label></td><td>%(fieldhi)s</td>' %
                           {'fieldlo': unicode(fieldlo),
                            'fieldhi': unicode(fieldhi),
                            'fieldhi_id': unicode(fieldhi.auto_id)})
                else:
                    row = (u'<tr><td style="text-align:right;"><label for="%(fieldid)s">%(label)s</label></td><td>%(ofield)s</td>' %
                           {'label': unicode(mfield.verbose_name),
                            'ofield': unicode(ofield),
                            'fieldid': unicode(ofield.auto_id[:-9])})
                    bfield = forms.forms.BoundField(self, self.fields[mfield.name], mfield.name)
                    row = (row + u'<td colspan=3>%(field)s</td>' %
                           {'field': unicode(bfield)})

                row = row + u'</tr>'
                output.append(row)
        return mark_safe(u'\n'.join(output))

    def modelVerboseName(self):
        return self.model._meta.verbose_name


def editFormFields(mymodel, field, enumerableFields):
    """
    Returns a dict of Form fields to add to an edit form, based on the model field
    """
    formfields = {}
    if maskField(field):
        pass  # nothing
    elif isinstance(field, VirtualIncludedField):
        pass # still need to cross this bridge
    else:
        widget = specialWidget(mymodel, field, enumerableFields)
        try:
            name = field.verbose_name
        except AttributeError:
            name = field.name
        valField = valueFormField(mymodel, field, widget, label=name)
        if valField is None:
            ## This must be class that we have missed of haven't gotten around to supporting/ignoring
            longname = '.'.join([field.__class__.__module__,
                                 field.__class__.__name__])
            print("EditForm doesn't deal with %s yet" % longname)
        elif widget == 'textbox' and isinstance(field, fields.related.RelatedField):
            print("Too many values to edit %s" % field.name)
        else:
            formfields[field.name] = valField

    return formfields


class EditForm(forms.Form):
    """
    Dynamically creates a form to edit the given item
    """
    def __init__(self, mymodel, *args, **kwargs):
        enumerableFields = kwargs.pop('enumerableFields', None)
        forms.Form.__init__(self, *args, **kwargs)
        self.model = mymodel

        for field in modelFields(mymodel):
            self.fields.update(editFormFields(mymodel, field, enumerableFields))


class SortForm(forms.Form):
    """
    Dynamically creates a form to sort over the given class
    """
    def __init__(self, mymodel, *args, **kwargs):
        forms.Form.__init__(self, *args, **kwargs)
        numorder = 5  # should be a passed in parameter
        self.model = mymodel
        sortingfields = []
        for x in modelFields(mymodel):
            if maskField(x):
                pass
            elif ordinalField(self.model, x):
                if x.verbose_name != "":
                    sortingfields.append(x)
        if len(sortingfields) > 1:
            datachoices = (tuple((None, 'None') for x in [1]) +
                           tuple((x.name, x.verbose_name)
                                 for x in sortingfields))
            for order in range(1, numorder + 1):
                self.fields['order' + str(order)] = forms.ChoiceField(choices=datachoices,
                                                                      initial=datachoices[0][0],
                                                                      required=True)
                self.fields['direction' + str(order)] = forms.ChoiceField(choices=(('ASC', 'Ascending'),
                                                                                   ('DESC', 'Descending')),
                                                                          widget=RadioSelect(),
                                                                          initial='ASC',
                                                                          required=True)


def SpecializedForm(formModel, myModel):
    """
    Returns form class using the given model, so you don't have to pass the model to the constructor. Helps with formsets
    """
    ## tmpFormClass is a SearchForm specialized on a specific model
    ## so we don't have to pass in the model
    ## so it can be used by formset_factory.
    ## Couldn't figure out how to pass the model arg to formset_factory;
    ## Tried to use type(,,), but couldn't get that to work either
    ## Tried to use functools.partial, but couldn't get that to work
    ## Ted S. suggested MetaClass, which could be a possibility
    tmpFormClass = type('tmpForm', (formModel,), dict())

    def initMethod(self, *args, **kwargs):
        formModel.__init__(self, myModel, *args, **kwargs)

    tmpFormClass.__init__ = initMethod
    return tmpFormClass


class AxesForm(forms.Form):
    """
    Dynamically creates the form to choose the axes and series of a corresponding plot
    """
    def __init__(self, mfields, *args, **kwargs):
        seriesablefields = kwargs.pop('seriesablefields', None)
        forms.Form.__init__(self, *args, **kwargs)
        chartablefields = []

        if (seriesablefields is None):
            seriesablePreset = False
            seriesablefields = []
            try:
                itemCount = tableSize(mfields[0].model)  # an upper bound
            except (IndexError,AttributeError):
                pass  # no fields, apparently
            try:
                maxseriesable = settings.XGDS_DATA_MAX_SERIESABLE
            except AttributeError:
                maxseriesable = 100
        else:
            seriesablePreset = True

        for x in mfields:
            if (not isinstance(x, VirtualIncludedField)) and (not maskField(x)):
                if ordinalField(x.model, x):
                    chartablefields.append(x)
                elif ((seriesablePreset) or
                      (isinstance(x, GenericForeignKey)) or
                      (isAbstract(x.model)) or
                      (itemCount is None)):
                    pass
                else:
                    estCount = fieldSize(x,
                                         tableSize(x.model),
                                          maxseriesable,
                                          maxseriesable * 1000)
                    if (estCount is not None) and (estCount <= maxseriesable):
                        seriesablefields.append(x)

        if len(chartablefields) > 1:
            datachoices = (tuple((x, x)
                                 for x in ['Rank']) +
                           tuple((x.name, x.verbose_name)
                                 for x in chartablefields))
            serieschoices = [(None, 'None')]
            for x in seriesablefields:
                if isinstance(x, fields.related.RelatedField):
                    serieschoices.append((x.name, x.verbose_name))
                else:
                    serieschoices.append((x.name, x.verbose_name))
            self.fields['xaxis'] = forms.ChoiceField(choices=datachoices,
                                                     required=True,
                                                     initial=chartablefields[0].name)
            self.fields['yaxis'] = forms.ChoiceField(choices=datachoices,
                                                     required=True,
                                                     initial=chartablefields[1].name)
            self.fields['series'] = forms.ChoiceField(choices=tuple(serieschoices),
                                                      required=True,
                                                      initial=serieschoices[0][0])
