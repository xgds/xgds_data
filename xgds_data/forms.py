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

import pytz
from django import forms
from django.db import models
from django.utils.safestring import mark_safe
from django.db.models import fields
#from django.forms.widgets import RadioSelect, TextInput
from django.forms.widgets import DateTimeInput
from django.forms import DateTimeField, ChoiceField
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.auth.models import User

from django.conf import settings
from xgds_data.models import VirtualIncludedField
from xgds_data.introspection import (modelFields, maskField, isOrdinalOveridden, isAbstract, pk, ordinalField, modelName, settingsForModel)
from xgds_data.DataStatistics import tableSize, fieldSize
from xgds_data.utils import label
from geocamTrack.forms import AbstractImportTrackedForm
from geocamUtil.extFileField import ExtFileField
try:
    from geocamUtil.loader import LazyGetModelByName
    GEOCAMUTIL_FOUND = True
except ImportError:
    GEOCAMUTIL_FOUND = False

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


# eh, is no one using this?
# def estimateFieldCount(field, itemCount, maxItemCount, maxFieldCount,
#                        queryGenerator=None):
#     """
#     How many values occur for this field?
#     """
#     estCount = None
#     try:
#         estCount = tableSize(field.rel.to)
#     except AttributeError:
#         if (itemCount < maxItemCount):
#             estCount = itemCount
#         elif (itemCount < maxFieldCount):
#             if queryGenerator:
#                 qset = queryGenerator(field.model).values(field.name).order_by().distinct().count()
#             else:
#                 estCount = field.model.objects.values(field.name).order_by().distinct().count()

#     return estCount


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


def toFieldName(model):
    """
    """
    ## the to_field is a difficult problem
    ## it controls what the options are to be selected
    ## ideally that would be the same as what the user sees
    ## but that is __unicode__(). So potentially there is
    ## a mismatch.
    ## If the __unicode__ is just a particular field, we can
    ## make it work. Below it is hardcoded if the model has
    ## a field "name" (cheesy), otherwise defaults to pk
    try:
        to_field_name = settingsForModel(settings.XGDS_DATA_TO_FIELD_NAME, model)[0]
    except (AttributeError, IndexError):
        to_field_name = None

    if not to_field_name:
        fieldnames = [x.name for x in modelFields(model)]
        if 'name' in fieldnames:
            return 'name'
        else:
            to_field_name = None # pk(field.rel.to).name
    return to_field_name


def valueFormField(mymodel, field, widget, allowMultiple=True, label=None,
                   queryGenerator=None):
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
        to_field_name = toFieldName(field.rel.to)

        if queryGenerator:
            qset = queryGenerator(field.related.model)
        else:
            qset = field.related.model.objects.all()
        if widget is 'pulldown':
            # can't use as queryset arg because it needs a queryset, not a list
            # foreigners = sorted(field.related.parent_model.objects.all(), key=lambda x: unicode(x))
            if (field.related.model == User):
                qset = qset.order_by('last_name')
            if isinstance(field, models.ManyToManyField) and allowMultiple:
                return forms.ModelMultipleChoiceField(queryset=qset,
                                                      to_field_name=to_field_name,
                                                      required=False,
                                                      label=label)
            else:
                return specialModelChoiceField(queryset=qset,
                                               # order_by('name'),
                                               empty_label="<Any>",
                                               required=False,
                                               label=label)
        else:
            return forms.CharField(required=False,label=label)
            # return forms.ModelChoiceField(queryset=qset,
            #                               to_field_name=to_field_name,
            #                               initial=None,
            #                               widget=forms.TextInput,
            #                               required=False,
            #                               label=label)
    else:
        return None


# doesn't do anything useful anymore
# def fieldNameBase(field,name):
#     """
#     Get the form field name
#     """
#     if isinstance(field, VirtualIncludedField):
#         return name
#     else:
#         return name

def searchFormFields(mymodel, field, enumerableFields,
                     queryGenerator=None):
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
            for name,ff in searchFormFields(tmfs[0].model, tmfs[0], enumerableFields, queryGenerator=queryGenerator).iteritems():
                vfields[name] = ff
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
            formfieldname = field.name
            if ordinalField(mymodel, field):
                formfields[formfieldname + '_lo'] = valueFormField(mymodel, field, widget, queryGenerator=queryGenerator)
                formfields[formfieldname + '_hi'] = valueFormField(mymodel, field, widget, queryGenerator=queryGenerator)
            else:
                vff = valueFormField(mymodel, field, widget, allowMultiple=False, queryGenerator=queryGenerator)
                if (widget != 'pulldown') and (isinstance(field, fields.related.RelatedField)):
                    to_field_name = toFieldName(field.rel.to)
                    if to_field_name is None:
                        to_field_name = pk(field.rel.to).name
                    formfieldname = '__'.join([formfieldname, to_field_name])
                formfields[formfieldname] = vff
            formfields[formfieldname + '_operator'] = opField

    return formfields


class SearchForm(forms.Form):
    """
    Dynamically creates a form to search the given class
    """
    def __init__(self, mymodel, *args, **kwargs):
        enumerableFields = kwargs.pop('enumerableFields', None)
        queryGenerator = kwargs.pop('queryGenerator', None)
        forms.Form.__init__(self, *args, **kwargs)
        self.model = mymodel

        for field in modelFields(mymodel):
            self.fields.update(searchFormFields(mymodel, field, enumerableFields, queryGenerator=queryGenerator))

    def as_table(self, expert=False):
        output = []

        fieldmap = dict([(f.name, f) for f in modelFields(self.model)])
        for ffield in self.fields:
            if ffield.endswith('_operator'):
                basename = ffield[:-(len('_operator'))]
                loname = basename + '_lo'
                hiname = basename + '_hi'
                mfield = fieldmap[basename.split('__')[0]]
                ofield = forms.forms.BoundField(self, self.fields[ffield], ffield)
                if not expert:
                    ofield = ofield.as_hidden()

                if (loname in self.fields) and (hiname in self.fields):
                    fieldlo = forms.forms.BoundField(self, self.fields[loname], loname)
                    fieldhi = forms.forms.BoundField(self, self.fields[hiname], hiname)
                    row = (u'<tr><td style="text-align:right;"><label for="%(fieldid)s">%(label)s</label></td><td>%(ofield)s</td>' %
                           {'label': unicode(mfield.verbose_name),
                               #'label': unicode(basename),
                            'ofield': unicode(ofield),
                            'fieldid': unicode(fieldlo.auto_id)
                            })
                    row = (row + u'<td>%(fieldlo)s</td><td><label for="%(fieldhi_id)s">up to</label></td><td>%(fieldhi)s</td>' %
                           {'fieldlo': unicode(fieldlo),
                            'fieldhi': unicode(fieldhi),
                            'fieldhi_id': unicode(fieldhi.auto_id)})
                else:
                    bfield = forms.forms.BoundField(self,
                                                    self.fields[basename],
                                                   basename)

                    row = (u'<tr><td style="text-align:right;"><label for="%(fieldid)s">%(label)s</label></td><td>%(ofield)s</td>' %
                           {'label': unicode(mfield.verbose_name),
                            #   'label': unicode(basename),
                            'ofield': unicode(ofield),
#                            'fieldid': unicode(ofield.auto_id[:-9])
                            'fieldid': unicode(bfield.auto_id)
                            })
                    row = (row + u'<td colspan=3>%(field)s</td>' %
                           {'field': unicode(bfield)})
                if row is not None:
                    row = row + u'</tr>'
                    output.append(row)

        return mark_safe(u'\n'.join(output))

    def as_expert_table(self):
        return self.as_table(expert=True)

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
        try:
            numorder = kwargs['num']
            del kwargs['num']
        except KeyError:
            numorder = 5
        try:
            directionWidget = kwargs['dwidget']
            del kwargs['dwidget']
        except KeyError:
            directionWidget = forms.RadioSelect

        forms.Form.__init__(self, *args, **kwargs)
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
                                                                          widget=directionWidget,
                                                                          initial='ASC',
                                                                          required=True)

    def orders(self):
        myorders = []
        x = 1
        good = True
        while good:
            try:
                order = 'order'+str(x)
                direction = 'direction'+str(x)
                if (self.cleaned_data[order] != 'None'):
                    if (self.cleaned_data[direction] == 'DESC'):
                        myorders.append('-'+self.cleaned_data[order])
                    else:
                        myorders.append(self.cleaned_data[order])
                x = x + 1
            except KeyError:
                good = False
        return myorders


def SpecializedForm(formModel, myModel, queryGenerator=None):
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
        if queryGenerator:
            kwargs['queryGenerator'] = queryGenerator
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


class ImportInstrumentDataForm(AbstractImportTrackedForm):
    date_formats = list(forms.DateTimeField.input_formats) + [
        '%Y/%m/%d %H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%m/%d/%Y %H:%M'
        ]
    dataCollectionTime = DateTimeField(label="Collection Time",
                                       input_formats=date_formats,
                                       required=False,
                                       )
    INSTRUMENT_MODEL = LazyGetModelByName(settings.XGDS_INSTRUMENT_INSTRUMENT_MODEL)
    instrumentChoices = [(i,e["displayName"]) for i,e in
                         enumerate(INSTRUMENT_MODEL.get().getInstrumentListWithImporters())]
    instrumentId = ChoiceField(choices=instrumentChoices, label="Instrument")
    portableDataFile = ExtFileField(ext_whitelist=(".spc",".txt",".csv" ),
                                    required=True,
                                    label="Portable Data File")
    manufacturerDataFile = ExtFileField(ext_whitelist=(".pdz",".a2r",".asd" ),
                                        required=True,
                                        label="Manufacturer Data File")

    def clean_dataCollectionTime(self):
        ctime = self.cleaned_data['dataCollectionTime']

        if not ctime:
            return None
        else:
            tz = self.getTimezone()
            naiveTime = ctime.replace(tzinfo=None)
            localizedTime = tz.localize(naiveTime)
            utctime = localizedTime.astimezone(pytz.utc)
            return utctime
