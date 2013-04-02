# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import sys
import re
import traceback
import csv

from django.shortcuts import render_to_response, render
from django.http import HttpResponseNotAllowed, HttpResponseRedirect, HttpResponseForbidden, Http404, HttpResponse
from django.template import RequestContext
from django.db import connection, DatabaseError

from xgds_data.models import getModelByName
from xgds_data.forms import QueryForm, SearchForm
from xgds_data import settings

from inspect import isclass, getmembers, getmodule
from django.db.models import Q
from django.db.models.fields import DateTimeField
from django.forms.fields import ChoiceField
from django.db.models.query import QuerySet
from django import forms
from django.forms.formsets import formset_factory

# from django import forms ## need to get this out of here and back into form

def getModelInfo(qualifiedName, model):
    return {
        'name': model.__name__,
        'qualifiedName': qualifiedName
    }

SEARCH_MODELS = dict([(name, getModelByName(name))
                      for name in settings.XGDS_DATA_SEARCH_MODELS])

MODELS_INFO = [getModelInfo(qualifiedName, model)
              for qualifiedName, model in SEARCH_MODELS.iteritems()]


def searchIndex(request):
    return render_to_response('xgds_data/searchIndex.html',
                              {'models': MODELS_INFO},
                              context_instance=RequestContext(request))


def searchModel(request, modelName):
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])

    model = SEARCH_MODELS[modelName]
    tableName = model._meta.db_table
    modelInfo = getModelInfo(modelName, model)

    fieldLookup = dict(((field.name, field)
                        for field in model._meta._fields()))
    timestampField = None
    for field in ('timestampSeconds', 'timestamp'):
        if field in fieldLookup:
            timestampField = field
            break

    if request.method == 'POST':
        form = QueryForm(request.POST)
        assert form.is_valid()
        userQuery = form.cleaned_data['query']
        escapedUserQuery = re.sub(r'%', '%%', userQuery)
        mostRecentFirst = form.cleaned_data['mostRecentFirst']

        prefix = 'SELECT * FROM %s ' % tableName
        countPrefix = 'SELECT COUNT(*) FROM %s ' % tableName
        order = ''
        if mostRecentFirst and timestampField:
            order += ' ORDER BY %s DESC ' % timestampField
        limit = ' LIMIT 100'

        countQuery = countPrefix + escapedUserQuery
        sqlQuery = prefix + escapedUserQuery + order + limit
        # escape % signs, interpreted by Django raw() as template format

        styledSql = (prefix
                     + '<span style="color: blue; font-weight: bold">%s</span>' % userQuery
                     + order
                     + limit)


        try:
            cursor = connection.cursor()
            cursor.execute(countQuery)
            count = cursor.fetchone()[0]

            matches = list(model.objects.raw(sqlQuery))

            wasError = False
        except DatabaseError:
            sys.stderr.write(traceback.format_exc())
            wasError = True
            result = {
                'sql': styledSql,
                'summary': 'database error!',
                'matches': [],
            }
        if not wasError:
            result = {
                'sql': styledSql,
                'summary': '%s matches (showing at most 100)' % count,
                'matches': matches,
            }
    else:
        # GET method
        form = QueryForm()
        result = None
    return render_to_response('xgds_data/searchModel.html',
                              {'model': modelInfo,
                               'models': MODELS_INFO,
                               'form': form,
                               'result': result},
                              context_instance=RequestContext(request))

def chooseSearchModel(request, moduleName):
    """
        List the models in the module, so they can be selected for search
        """
    modelmodule = __import__('.'.join([moduleName,'models'])).models
    mymodels = [(x,y) for x,y in getmembers(modelmodule,predicate=isclass) if (getmodule(y) == modelmodule) ]

    return render(request,'xgds_data/chooseSearchModel.html', 
                  {'title': 'Search '+moduleName,
                   'module': moduleName,
                   'models' : mymodels}
                  )
    
def csvEncode(something):
    """
        csvlib can't deal with non-ascii unicode, thus, this function
        """
    if (isinstance(something,unicode)) :
        return something.encode("ascii", errors='xmlcharrefreplace')
        # return something.encode("utf-8")
    else :
        return something
    
def specializedSearchForm(myModel) :
    ## tmpFormClass is a SearchForm specialized on a specific model
    ## so we don't have to pass in the model
    ## so it can be used by formset_factory.
    ## Couldn't figure out how to pass the model arg to formset_factory;
    ## Tried to use type(,,), but couldn't get that to work either
    ## Tried to use functools.partial, but couldn't get that to work
    ## Ted S. suggested MetaClass, which could be a possibility
    tmpFormClass = type('tmpForm', (SearchForm,), dict())
    tmpFormClass.__init__ = lambda self, *args, **kwargs : SearchForm.__init__(self,myModel,*args,**kwargs)         
    return tmpFormClass

def formsetifyFieldName(i,fname):
    return '-'.join(['form',str(i),fname])

def formsetDateTimeFields(fields,formCount) :
    datetimefields = []
    for x in fields :
        if isinstance(x,DateTimeField) :
            for y in range(0,formCount+1) :
                datetimefields.append(formsetifyFieldName(y,x.name))
    return datetimefields

def searchChosenModel(request, moduleName, modelName):
    """
        Search over the fields of the selected model
        """
    modelmodule = __import__('.'.join([moduleName,'models'])).models
    myModel = getattr(modelmodule,modelName)
    tmpFormClass = specializedSearchForm(myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    debug = []
    formset = False
    if request.method == 'POST' :
        data = request.POST;
    else:
        data = request.GET
    formCount = 1
    mode = data.get('mode',False)
    if (mode == 'addform') :
        formCount = int(data['form-TOTAL_FORMS'])
        foo = tmpFormClass()      
        newdata = data.copy()
        for fname, field in foo.fields.iteritems() :
            if isinstance(field.initial,QuerySet) :
                val = [ unicode(x.id) for x in field.initial ]
                newdata.setlist(formsetifyFieldName(formCount,fname),val)
            elif ((not isinstance(field,ChoiceField)) & (not field.initial)) :
                newdata[formsetifyFieldName(formCount,fname)] = unicode('')
            else :
                newdata[formsetifyFieldName(formCount,fname)] = unicode(field.initial)
        newdata['form-TOTAL_FORMS'] = unicode(formCount  + 1 ) 
        formset = tmpFormSet(newdata) # but passing data nullifies extra
        response = render(request,'xgds_data/searchChosenModel.html', 
                              {'title': 'Search '+modelName,
                               'module': moduleName,
                               'model': modelName,
                               'debug' :  debug,
                               'datetimefields' : formsetDateTimeFields(myModel._meta.fields,formCount),
                               "formset" : formset},
                              )  
    elif (mode) : # determines if this is first time or not
        formCount = int(data['form-TOTAL_FORMS'])
        formset = tmpFormSet(data)
        #form = SearchForm(data=data,mymodel=myModel)
        if formset.is_valid():  
            filters = Q()
            ## forms are interpreted as internally conjunctive, externally disjunctive
            for form in formset:
                subfilter = Q()
                for field in form.cleaned_data :
                    if form.cleaned_data[field] != None:
                        if field.endswith('_lo') :
                            clause = { field[:-3]+'__gte' : form.cleaned_data[field] }
                            subfilter &= Q(**clause)
                        elif field.endswith('_hi') :
                            clause = { field[:-3]+'__lte' : form.cleaned_data[field] }
                            subfilter &= Q(**clause)
                        elif (isinstance(form[field].field,forms.ModelMultipleChoiceField)):
                            clause = { field+'__in' : form.cleaned_data[field] }
                            subfilter &= Q(**clause)
                            #debug.append([x.id for x in form.cleaned_data[field]])
                        elif (isinstance(form[field].field,forms.ModelChoiceField)):
                            clause = { field+'__exact' : form.cleaned_data[field] }
                            subfilter &= Q(**clause)
                            #debug.append([x.__class__ for x in form.cleaned_data[field]])
                        elif (isinstance(form[field].field,forms.ChoiceField)):
                            if (form.cleaned_data[field]  == 'True') :
                                clause = { field+'__gt' : form.cleaned_data[field] }
                                subfilter &= Q(**clause)
                            elif (form.cleaned_data[field]  == 'False') :
                                clause = { field+'__exact' : 0 }
                                subfilter &= Q(**clause)
                        else :
                            clause = { field+'__icontains' : form.cleaned_data[field] }
                            subfilter &= Q(**clause)
                filters |= subfilter           
    
            #debug = [ (x,form.errors[x]) for x in form.errors ]
            #dfilters = dict(filters)
            if (mode == 'csv') :
                results = myModel.objects.filter(filters).all()
                fields = [f.column for f in myModel._meta.fields ]      
                response = HttpResponse(content_type='text/csv')
                # if you want to download instead of display in browser  
                # response['Content-Disposition'] = 'attachment; filename='+modelName+'.csv'
                writer = csv.writer(response)
                writer.writerow(fields)
                for r in results:
                    writer.writerow( [csvEncode(getattr(r,f)) for f in fields if hasattr(r,f) ] )
            else :
                response = render(request,'xgds_data/searchChosenModel.html', 
                                      {'title': 'Search '+modelName,
                                       'module': moduleName,
                                       'model': modelName,
                                       'debug' :  debug,
                                       'count' : myModel.objects.filter(filters).count(),
                                       'datetimefields' : formsetDateTimeFields(myModel._meta.fields,formCount),
                                       "formset" : formset},
                                      )
        else:
            debug = [ (x,formset.errors[x]) for x in formset.errors ]

    if (not formset) :
        formset = tmpFormSet()
        response = render(request,'xgds_data/searchChosenModel.html', 
                              {'title': 'Search '+modelName,
                               'module': moduleName,
                               'model': modelName,
                               'debug' :  debug,
                               'datetimefields' : formsetDateTimeFields(myModel._meta.fields,formCount),
                               "formset" : formset},
                              )           

    return response
