# __BEGIN_LICENSE__
# Copyright (C) 2008-2014 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from django import forms
from django.db.models import fields
from django.utils.safestring import mark_safe
from django.db.models.fields.related import RelatedField
from django.forms.widgets import RadioSelect, TextInput
from django.contrib.contenttypes.generic import ContentType, GenericForeignKey

from xgds_data import settings
from xgds_data.models import VirtualIncludedField
from xgds_data.introspection import modelFields, maskField, isOrdinalOveridden, isAbstract, pk, ordinalField
# pylint: disable=R0924

class QueryForm(forms.Form):
    query = forms.CharField(max_length=256, required=False,
                            widget=forms.TextInput(attrs={'size': 100}))
    mostRecentFirst = forms.BooleanField(label='Most recent first',
                                         required=False,
                                         initial=True)


def formFields(mymodel, field, enumerableFields):
    """
    Returns a dict of Form fields to add to the form, based on the model field
    """
    rangeOperators = (('IN~', 'IN~'),
                      ('IN', 'IN'),
                      ('NOT IN', 'NOT IN'))
    categoricalOperators = (('=', '='),
                            ('!=', '!='))
    stringOperators = (#('=~', '=~'),
                       ('=', '='),
                       ('!=', '!='))
    formfields = {}
    if maskField(field):
        pass  # nothing
    elif isinstance(field, VirtualIncludedField):
        tmfs = field.targetFields()
        if len(tmfs):
            ## need to assume all are the same, so just use the first one
            formfields.update(formFields(tmfs[0].model, tmfs[0], enumerableFields))
    elif ordinalField(mymodel, field):
        formfields[field.name + '_operator'] = \
            forms.ChoiceField(choices=rangeOperators,
                              initial=rangeOperators[0][0],
                              required=True)
        if isinstance(field, fields.DateTimeField):
            formfields[field.name + '_lo'] = forms.DateTimeField(required=False)
            formfields[field.name + '_hi'] = forms.DateTimeField(required=False)
        elif isinstance(field, (fields.DecimalField, fields.FloatField)):
            formfields[field.name + '_lo'] = forms.FloatField(required=False)
            formfields[field.name + '_hi'] = forms.FloatField(required=False)
        elif isinstance(field, fields.PositiveIntegerField):
            formfields[field.name + '_lo'] = forms.IntegerField(min_value=1,
                                   required=False)
            formfields[field.name + '_hi'] = forms.IntegerField(min_value=1,
                                   required=False)
        elif isinstance(field, fields.IntegerField):
            formfields[field.name + '_lo'] = forms.IntegerField(required=False)
            formfields[field.name + '_hi'] = forms.IntegerField(required=False)                
        
    elif isinstance(field, (fields.AutoField, fields.CharField, fields.TextField)) or isOrdinalOveridden(mymodel, field):
        formfields[field.name + '_operator'] = \
            forms.ChoiceField(choices=stringOperators,
                              initial=stringOperators[0][0],
                              required=True)
        formfields[field.name] = forms.CharField(required=False)
    elif isinstance(field, (fields.BooleanField, fields.NullBooleanField)):
        formfields[field.name + '_operator'] = \
            forms.ChoiceField(choices=categoricalOperators,
                              initial=categoricalOperators[0][0],
                              required=True)
        formfields[field.name] = \
            forms.ChoiceField(choices=((None, '<Any>'),
                                       (True, True),
                                       (False, False)),
                              required=False)
    
    elif (isinstance(field, fields.related.ForeignKey) or
          isinstance(field, fields.related.ManyToManyField)):
        widget = None
        relModel = field.rel.to
        if (relModel == 'self'):
            relModel = field.model
        
        if enumerableFields:
            if (field in enumerableFields):
                widget = 'pulldown'
        elif (not isAbstract(relModel)):
            try:
                maxpulldown = settings.XGDS_DATA_MAX_PULLDOWNABLE
            except:
                maxpulldown = 100
            if (relModel.objects.count() <= maxpulldown) or \
                    (not isAbstract(mymodel) and \
                   (field.model.objects.values(field.name).order_by().distinct().count() <= maxpulldown)):
                widget = 'pulldown'
            else:
                widget = 'textbox'
            
        if widget is 'pulldown':
            formfields[field.name + '_operator'] = \
                forms.ChoiceField(choices=categoricalOperators,
                                  initial=categoricalOperators[0][0],
                                  required=True)
            # can't use as queryset arg because it needs a queryset, not a list
            #foreigners = sorted(field.related.parent_model.objects.all(), key=lambda x: unicode(x))
            qset = field.related.parent_model.objects.all()
            formfields[field.name] = \
                forms.ModelChoiceField(queryset=qset,
                                       initial=qset,
                                       # order_by('name'),
                                       empty_label="<Any>",
                                       required=False)
        elif widget is 'textbox':
            formfields[field.name + '_operator'] = \
                forms.ChoiceField(choices=stringOperators,
                                  initial=stringOperators[0][0],
                                  required=True)
            qset = field.related.parent_model.objects.all()
            try:
                to_field = [x for x in modelFields(field.rel.to) if x.name == 'name'][0]
            except:
                to_field = pk(field.rel.to)
            formfields[field.name] = \
                forms.ModelChoiceField(queryset=qset,
                                       to_field_name=to_field.name,
                                       initial=None,
                                       widget=TextInput,
                                       required=False)
            # self.fields[field.name] = forms.CharField(required=False)
    else:
        ##self.fields[field.name + '_operator'] = \
        ##    forms.ChoiceField(choices=categoricalOperators,
        ##                      initial=categoricalOperators[0][0],
        ##                      required=True)
        ## that can't be the right way to get the name
        longname = '.'.join([field.__class__.__module__,
                             field.__class__.__name__])
        print("Search doesn't deal with %s yet" % longname)
        ## put the field name in as the default just to tell me, the programmer, that this
        ## class isn't properly dealt with yet.
        ##self.fields[field.name] = \
        ##    forms.CharField(initial=longname,
        ##                    required=False)
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
            self.fields.update(formFields(mymodel, field, enumerableFields))

    def as_table(self):
        output = []

        for mfield in modelFields(self.model):
            ## self.model._meta.fields:
            #n = mfield.name
            fieldname = mfield.name
            ##if (isinstance(mfield,VirtualIncludedField)):
            ##    fieldname = mfield.compound_name()
            if (fieldname in self.fields or
                ((fieldname + '_lo') in self.fields and
                 (fieldname + '_hi') in self.fields)):
                ofieldname = fieldname + '_operator'
                ofield = forms.forms.BoundField(self, self.fields[ofieldname], ofieldname)
                row = (u'<tr><td style="text-align:right; font-weight:bold;">%(label)s</td><td>%(ofield)s</td>' %
                       {'label': unicode(mfield.verbose_name),
                        'ofield': unicode(ofield.as_hidden())
                        })
                if ordinalField(self.model, mfield):
                    loname, hiname = fieldname + '_lo', fieldname + '_hi'
                    fieldlo = forms.forms.BoundField(self, self.fields[loname], loname)
                    fieldhi = forms.forms.BoundField(self, self.fields[hiname], hiname)
                    row = (row + u'<td>%(fieldlo)s</td><td>up to</td><td>%(fieldhi)s</td>' %
                           {'fieldlo': unicode(fieldlo),
                            'fieldhi': unicode(fieldhi)})
                else:
                    bfield = forms.forms.BoundField(self, self.fields[fieldname],
                                                    fieldname)
                    row = (row + u'<td colspan=3>%(field)s</td>' %
                           {'field': unicode(bfield)})

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
                row = (u'<tr><td style="text-align:right; font-weight:bold;">%(label)s</td><td>%(ofield)s</td>' %
                       {'label': unicode(mfield.verbose_name),
                        'ofield': unicode(ofield)})
                if ordinalField(self.model, mfield):
                    loname, hiname = mfield.name + '_lo', mfield.name + '_hi'
                    fieldlo = forms.forms.BoundField(self, self.fields[loname], loname)
                    fieldhi = forms.forms.BoundField(self, self.fields[hiname], hiname)
                    row = (row + u'<td>%(fieldlo)s</td><td>up to</td><td>%(fieldhi)s</td>' %
                           {'fieldlo': unicode(fieldlo),
                            'fieldhi': unicode(fieldhi)})
                else:
                    bfield = forms.forms.BoundField(self, self.fields[mfield.name],
                                                    mfield.name)
                    row = (row + u'<td colspan=3>%(field)s</td>' %
                           {'field': unicode(bfield)})

                row = row + u'</tr>'
                output.append(row)
        return mark_safe(u'\n'.join(output))

    def modelVerboseName(self):
        return self.model._meta.verbose_name


class SortForm(forms.Form):
    """
    Dynamically creates a form to sort over the given class
    """
    def __init__(self, mymodel, *args, **kwargs):
        forms.Form.__init__(self, *args, **kwargs)
        numorder = 5 ## should be a passed in parameter
        self.model = mymodel
        sortingfields = []
        for x in modelFields(mymodel):
            if maskField(x):
                pass
            elif ordinalField(self.model, x):
                if x.verbose_name != "":
                    sortingfields.append(x)
        if len(sortingfields) > 1:
            datachoices = (tuple((None, 'None') for x in [1])  +
                           tuple((x.name, x.verbose_name)
                                 for x in sortingfields))
            for order in range(1,numorder+1):
                self.fields['order'+str(order)] = forms.ChoiceField(choices=datachoices,
                                                                    initial=datachoices[0][0],
                                                                    required=True)
                self.fields['direction'+str(order)] = forms.ChoiceField(choices=(('ASC','Ascending'),
                                                                                 ('DESC','Descending')),
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
        for x in mfields:
            if (not isinstance(x, VirtualIncludedField)) and ordinalField(x.model, x) and (not maskField(x)):
                chartablefields.append(x)
        if (seriesablefields is None):
            try:
                maxseriesable = settings.XGDS_DATA_MAX_SERIESABLE
            except:
                maxseriesable = 100
            seriesablefields = []

            for x in mfields:
                if ((not isinstance(x, (GenericForeignKey, VirtualIncludedField))) and
                    (not ordinalField(x.model, x)) and
                    (not maskField(x)) and
                    (not isAbstract(x.model)) and
                    (x.model.objects.values(x.name).order_by().distinct().count() <= maxseriesable)):
                    seriesablefields.append(x)
        if len(chartablefields) > 1:
            datachoices = (tuple((x, x)
                                 for x in ['Rank']) +
                           tuple((x.name, x.verbose_name)
                                 for x in chartablefields))
            serieschoices = [(None, 'None')]
            for x in seriesablefields:
                if isinstance(x, RelatedField):
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
