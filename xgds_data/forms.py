# __BEGIN_LICENSE__
# Copyright (C) 2008-2014 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from django import forms
from django.db.models import fields
from django.utils.safestring import mark_safe
from django.db.models.fields.related import RelatedField

from xgds_data.introspection import modelFields
# pylint: disable=R0924


class QueryForm(forms.Form):
    query = forms.CharField(max_length=256, required=False,
                            widget=forms.TextInput(attrs={'size': 100}))
    mostRecentFirst = forms.BooleanField(label='Most recent first',
                                         required=False,
                                         initial=True)


class SearchForm(forms.Form):
    """
    Dynamically creates a form to search the given class
    """
    def __init__(self, mymodel, *args, **kwargs):
        enumerableFields = kwargs.pop('enumerableFields', None)
        forms.Form.__init__(self, *args, **kwargs)
        self.model = mymodel
        rangeOperators = (('IN~', 'IN~'),
                          ('IN', 'IN'),
                          ('NOT IN', 'NOT IN'))
        categoricalOperators = (('=', '='),
                                ('!=', '!='))
        for field in (modelFields(mymodel)):
            if isinstance(field, fields.AutoField):
                pass  # nothing
            elif isinstance(field, (fields.BooleanField, fields.NullBooleanField)):
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=categoricalOperators,
                                      initial=categoricalOperators[0][0],
                                      required=True)
                self.fields[field.name] = \
                    forms.ChoiceField(choices=((None, '<Any>'),
                                               (True, True),
                                               (False, False)),
                                      required=True)
            elif isinstance(field, fields.DateTimeField):
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=rangeOperators,
                                      initial=rangeOperators[0][0],
                                      required=True)
                self.fields[field.name + '_lo'] = forms.DateTimeField(required=False)
                self.fields[field.name + '_hi'] = forms.DateTimeField(required=False)
            elif isinstance(field, fields.CharField):
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=categoricalOperators,
                                      initial=categoricalOperators[0][0],
                                      required=True)
                self.fields[field.name] = forms.CharField(required=False)
            elif isinstance(field, fields.FloatField):
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=rangeOperators,
                                      initial=rangeOperators[0][0],
                                      required=True)
                self.fields[field.name + '_lo'] = forms.FloatField(required=False)
                self.fields[field.name + '_hi'] = forms.FloatField(required=False)
            elif (isinstance(field, fields.related.ForeignKey) or
                  isinstance(field, fields.related.ManyToManyField)):
                if ((enumerableFields and (field in enumerableFields)) or
                    ((enumerableFields is None) and
                     field.model.objects.values(field.name).order_by().distinct().count() <= 1000)):
                    self.fields[field.name + '_operator'] = \
                        forms.ChoiceField(choices=categoricalOperators,
                                          initial=categoricalOperators[0][0],
                                          required=True)
                    # can't use as queryset arg because it needs a queryset, not a list
                    #foreigners = sorted(field.related.parent_model.objects.all(), key=lambda x: unicode(x))
                    qset = field.related.parent_model.objects.all()
                    self.fields[field.name] = \
                        forms.ModelChoiceField(queryset=qset,
                                               initial=qset,
                                               # order_by('name'),
                                               empty_label="<Any>",
                                               required=False)
                else:
                    ## should deal with differently, probably text box
                    pass
            elif isinstance(field, fields.PositiveIntegerField):
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=rangeOperators,
                                      initial=rangeOperators[0][0],
                                      required=True)
                self.fields[field.name + '_lo'] = \
                    forms.IntegerField(min_value=1,
                                       required=False)
                self.fields[field.name + '_hi'] = \
                    forms.IntegerField(min_value=1,
                                       required=False)
            elif isinstance(field, fields.IntegerField):
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=rangeOperators,
                                      initial=rangeOperators[0][0],
                                      required=True)
                self.fields[field.name + '_lo'] = forms.IntegerField(required=False)
                self.fields[field.name + '_hi'] = forms.IntegerField(required=False)
            elif isinstance(field, fields.TextField):
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=categoricalOperators,
                                      initial=categoricalOperators[0][0],
                                      required=True)
                self.fields[field.name] = forms.CharField(required=False)
            else:
                self.fields[field.name + '_operator'] = \
                    forms.ChoiceField(choices=categoricalOperators,
                                      initial=categoricalOperators[0][0],
                                      required=True)
                ## that can't be the right way to get the name
                longname = '.'.join([field.__class__.__module__,
                                     field.__class__.__name__])
                ## put the field name in as the default just to tell me, the programmer, that this
                ## class isn't properly dealt with yet.
                self.fields[field.name] = \
                    forms.CharField(initial=longname,
                                    required=False)

    def as_table(self):
        output = []

        for mfield in self.model._meta.fields:
            n = mfield.name
            if (n in self.fields or
                ((n + '_lo') in self.fields and
                 (n + '_hi') in self.fields)):
                ofieldname = n + '_operator'
                ofield = forms.forms.BoundField(self, self.fields[ofieldname], ofieldname)
                row = (u'<tr><td style="text-align:right; font-weight:bold;">%(label)s</td><td>%(ofield)s</td>' %
                       {'label': unicode(mfield.verbose_name),
                        'ofield': unicode(ofield.as_hidden())
                        })
                if isinstance(mfield, (fields.DateTimeField,
                                       fields.FloatField,
                                       fields.IntegerField,
                                       fields.PositiveIntegerField)):
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

    def as_expert_table(self):
        output = []

        for mfield in self.model._meta.fields:
            n = mfield.name
            if (n in self.fields or
                ((n + '_lo') in self.fields and
                 (n + '_hi') in self.fields)):
                ofieldname = n + '_operator'
                ofield = forms.forms.BoundField(self, self.fields[ofieldname], ofieldname)
                row = (u'<tr><td style="text-align:right; font-weight:bold;">%(label)s</td><td>%(ofield)s</td>' %
                       {'label': unicode(mfield.name),
                        'ofield': unicode(ofield)})
                if isinstance(mfield, (fields.DateTimeField,
                                       fields.FloatField,
                                       fields.IntegerField,
                                       fields.PositiveIntegerField)):
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
    def __init__(self, mfields, *args, **kwargs):
        forms.Form.__init__(self, *args, **kwargs)
        sortingfields = []
        for x in mfields:
            if isinstance(x, fields.AutoField):
                pass
            elif isinstance(x, (fields.DateField,
                                fields.DecimalField,
                                fields.FloatField,
                                fields.IntegerField,
                                fields.TimeField)):
                sortingfields.append(x)

        if len(sortingfields) > 1:
            datachoices = (tuple((None, 'None')
                                 for x in ['Rank']) +
                           tuple((x.name, x.verbose_name)
                                 for x in sortingfields))
            self.fields['order'] = forms.ChoiceField(choices=datachoices,
                                                     required=True,
                                                     initial=sortingfields[0].name)


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
            if isinstance(x, (fields.DateField,
                              fields.DecimalField,
                              fields.FloatField,
                              fields.IntegerField,
                              fields.TimeField)):
                chartablefields.append(x)
        if (seriesablefields is None):
            seriesablefields = []
            for x in mfields:
                if ((not isinstance(x, (fields.AutoField, fields.DateField,
                                        fields.DecimalField,
                                        fields.FloatField,
                                        fields.IntegerField,
                                        fields.TimeField))) and
                        (x.model.objects.values(x.name).order_by().distinct().count() <= 100)):
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
