# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from django import forms
from django.forms.util import ErrorList
from django.db.models import fields
from django.utils.safestring import mark_safe
from django.db.models.fields import AutoField, DateField, DecimalField, FloatField, IntegerField, TimeField
from django.db.models.fields.related import RelatedField

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
    def __init__(self,mymodel,*args,**kwargs):
        forms.Form.__init__(self,*args,**kwargs)
        self.model = mymodel
        rangeOperators = (('IN~','IN~'),('IN','IN'),('NOT IN','NOT IN'))
        categoricalOperators = (('=','='), ('!=','!='))
        for field in (mymodel._meta.fields):
            if (isinstance(field,fields.AutoField)) :
                pass ## nothing
            elif (isinstance(field, fields.BooleanField)) :
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=categoricalOperators,
                                                                        initial=categoricalOperators[0][0],
                                                            required=True)
                self.fields[field.name] = forms.ChoiceField(choices=
                                                            ((None,'<Any>'),
                                                             (True, True),
                                                             (False, False)),
                                                            required=True)
            elif (isinstance(field, fields.DateTimeField)) :
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=rangeOperators,
                                                                        initial=rangeOperators[0][0],
                                                            required=True)
                self.fields[field.name+'_lo'] = forms.DateTimeField(required=False)
                self.fields[field.name+'_hi'] = forms.DateTimeField(required=False)
            elif (isinstance(field, fields.CharField)) :
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=categoricalOperators,
                                                                        initial=categoricalOperators[0][0],
                                                            required=True)
                self.fields[field.name] = forms.CharField(required=False)
            elif (isinstance(field, fields.FloatField)) :
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=rangeOperators,
                                                                        initial=rangeOperators[0][0],
                                                            required=True)
                self.fields[field.name+'_lo'] = forms.FloatField(required=False)
                self.fields[field.name+'_hi'] = forms.FloatField(required=False)
            elif (isinstance(field, fields.related.ForeignKey)) :
                if (field.model.objects.values(field.name).order_by().distinct().count() > 1000) :
                    ## should deal with differently, probably text box
                    pass
                else :
                    self.fields[field.name+'_operator'] = forms.ChoiceField(choices=categoricalOperators,
                                                                            initial=categoricalOperators[0][0],
                                                                required=True)
                    # can't use as queryset arg because it needs a queryset, not a list
                    #foreigners = sorted(field.related.parent_model.objects.all(), key=lambda x: unicode(x))
                    self.fields[field.name] = forms.ModelChoiceField(queryset=field.related.parent_model.objects.all(),
                                                                             initial=field.related.parent_model.objects.all(),
    #                                                                     order_by('name'),
                                                                     empty_label="<Any>",
                                                                     required = False)
            elif (isinstance(field, fields.PositiveIntegerField)) :
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=rangeOperators,
                                                                        initial=rangeOperators[0][0],
                                                            required=True)
                self.fields[field.name+'_lo'] = forms.IntegerField(min_value=1,required=False)
                self.fields[field.name+'_hi'] = forms.IntegerField(min_value=1,required=False)
            elif (isinstance(field, fields.IntegerField)) :
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=rangeOperators,
                                                                        initial=rangeOperators[0][0],
                                                            required=True)
                self.fields[field.name+'_lo'] = forms.IntegerField(required=False)
                self.fields[field.name+'_hi'] = forms.IntegerField(required=False)
            elif (isinstance(field, fields.TextField)) :
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=categoricalOperators,
                                                                        initial=categoricalOperators[0][0],
                                                            required=True)
                self.fields[field.name] = forms.CharField(required=False)
            else:
                self.fields[field.name+'_operator'] = forms.ChoiceField(choices=categoricalOperators,
                                                                        initial=categoricalOperators[0][0],
                                                            required=True)
                ## that can't be the right way to get the name
                longname = '.'.join([field.__class__.__module__,field.__class__.__name__])
                ## put the field name in as the default just to tell me, the programmer, that this
                ## class isn't properly dealt with yet.
                self.fields[field.name] = forms.CharField(initial=longname,required=False)
                                   
    def as_table(self):
        output  = []       
            
        for mfield in self.model._meta.fields :
            if (self.fields.has_key(mfield.name) or
                (self.fields.has_key(mfield.name+'_lo') and
                 self.fields.has_key(mfield.name+'_hi'))) :
                ofieldname = mfield.name+'_operator'
                ofield = forms.forms.BoundField(self,self.fields[ofieldname],ofieldname)
                row = u'<tr><td style="text-align:right; font-weight:bold;">%(label)s</td><td>%(ofield)s</td>' %  { 
                                                                'label': unicode(mfield.verbose_name), 
                                                                'ofield' :  unicode(ofield.as_hidden()) }
                if ((isinstance(mfield, fields.DateTimeField)) or 
                    (isinstance(mfield, fields.FloatField)) or
                    (isinstance(mfield, fields.IntegerField)) or
                    (isinstance(mfield, fields.PositiveIntegerField))) :
                    loname, hiname = mfield.name+'_lo', mfield.name+'_hi'
                    fieldlo = forms.forms.BoundField(self,self.fields[loname],loname)
                    fieldhi = forms.forms.BoundField(self,self.fields[hiname],hiname)
                    row = row + u'<td>%(fieldlo)s</td><td>up to</td><td>%(fieldhi)s</td>' %  { 
                        'fieldlo': unicode(fieldlo), 'fieldhi': unicode(fieldhi) }
                else :
                    bfield = forms.forms.BoundField(self,self.fields[mfield.name],mfield.name)
                    row = row + u'<td colspan=3>%(field)s</td>' %  { 'field': unicode(bfield) }
                    
                row = row + u'</tr>'
                output.append(row)            
        return mark_safe(u'\n'.join(output))
    
    def as_expert_table(self):
        output  = []       
            
        for mfield in self.model._meta.fields :
            if (self.fields.has_key(mfield.name) or
                (self.fields.has_key(mfield.name+'_lo') and
                 self.fields.has_key(mfield.name+'_hi'))) :
                ofieldname = mfield.name+'_operator'
                ofield = forms.forms.BoundField(self,self.fields[ofieldname],ofieldname)
                row = u'<tr><td style="text-align:right; font-weight:bold;">%(label)s</td><td>%(ofield)s</td>' %  { 
                                                                'label': unicode(mfield.name), 'ofield' :  unicode(ofield) }
                if ((isinstance(mfield, fields.DateTimeField)) or 
                    (isinstance(mfield, fields.FloatField)) or
                    (isinstance(mfield, fields.IntegerField)) or
                    (isinstance(mfield, fields.PositiveIntegerField))) :
                    loname, hiname = mfield.name+'_lo', mfield.name+'_hi'
                    fieldlo = forms.forms.BoundField(self,self.fields[loname],loname)
                    fieldhi = forms.forms.BoundField(self,self.fields[hiname],hiname)
                    row = row + u'<td>%(fieldlo)s</td><td>up to</td><td>%(fieldhi)s</td>' %  { 
                        'fieldlo': unicode(fieldlo), 'fieldhi': unicode(fieldhi) }
                else :
                    bfield = forms.forms.BoundField(self,self.fields[mfield.name],mfield.name)
                    row = row + u'<td colspan=3>%(field)s</td>' %  { 'field': unicode(bfield) }
                    
                row = row + u'</tr>'
                output.append(row)            
        return mark_safe(u'\n'.join(output))

class AxesForm(forms.Form):
    """
        Dynamically creates the form to choose the axes and series of a corresponding plot
        """
    def __init__(self,modelFields,*args,**kwargs):
        forms.Form.__init__(self,*args,**kwargs)
        chartablefields = []
        seriesablefields = []
        for x in modelFields :
            if (isinstance(x,DateField) or
                isinstance(x,DecimalField) or
                isinstance(x,FloatField) or
                isinstance(x,IntegerField) or
                isinstance(x,TimeField)) :
                chartablefields.append(x)
            elif ((not isinstance(x,AutoField)) and (x.model.objects.values(x.name).order_by().distinct().count() <= 100)) :
                seriesablefields.append(x);
        if (len(chartablefields) > 1) :
            datachoices = tuple( (x,x) for x in ['Rank']) + tuple( (x.name,x.name) for x in chartablefields)
            serieschoices = [(None,'None')]
            for x in seriesablefields :
                if isinstance(x,RelatedField) :
                    serieschoices.append( (x.name+'_id',x.name) )
                else :
                    serieschoices.append( (x.name, x.name) )
            self.fields['xaxis'] = forms.ChoiceField(choices=datachoices,required=True,initial=chartablefields[0].name)
            self.fields['yaxis'] = forms.ChoiceField(choices=datachoices,required=True,initial=chartablefields[1].name)
            self.fields['series'] = forms.ChoiceField(choices=tuple(serieschoices),required=True,initial=serieschoices[0][0])

        