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
from django.db.models.fields import DateTimeField
from django import forms
from django.utils.http import urlencode

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

def searchChosenModel(request, moduleName, modelName):
    """
        Search over the fields of the selected model
        """
    modelmodule = __import__('.'.join([moduleName,'models'])).models
    myModel = getattr(modelmodule,modelName)
    debug = []
    dfilters = {}
    rcount = None
    if request.method == 'POST' :
        form = SearchForm(data=request.POST,mymodel=myModel)
        if form.is_valid():  
            filters = []
            for field in form.cleaned_data :
                if form.cleaned_data[field] != None:
                    if field.endswith('_lo') :
                        filters.append((field[:-3]+'__gte',form.cleaned_data[field]))
                    elif field.endswith('_hi') :
                        filters.append((field[:-3]+'__lte',form.cleaned_data[field]))
                        debug.append(form.cleaned_data[field].__class__)
                    elif (form[field].field.__class__ ==  forms.ModelChoiceField):
                        ## we don't need to explicitly call .id below for the initial query,
                        ## but it is needed for the csv later
                        filters.append((field+'__exact',form.cleaned_data[field].id))
                        debug.append(form.cleaned_data[field].__class__)
                    elif (form[field].field.__class__ ==  forms.ChoiceField):
                        if (form.cleaned_data[field]  == 'True') :
                            filters.append((field+'__gt',0))
                        elif (form.cleaned_data[field]  == 'False') :
                            filters.append((field+'__exact',0))
                    else :
                        filters.append((field+'__icontains',form.cleaned_data[field]))             

            debug = [ (x,form.errors[x]) for x in form.errors ]
            dfilters = dict(filters)
            rcount = myModel.objects.filter(**dfilters).count()
        else:
            debug = [ (x,form.errors[x]) for x in form.errors ]
            form = SearchForm(mymodel=myModel)
    else:
        form = SearchForm(mymodel=myModel)

    return render(request,'xgds_data/searchChosenModel.html', 
                                      {'title': 'Search '+modelName,
                                       'module': moduleName,
                                       'model': modelName,
                                       'debug' :  debug,
                                       'count' : rcount,
                                       'csvargs' : urlencode(dfilters),
                                       'datetimefields' : [x.name for x in myModel._meta.fields if isinstance(x,DateTimeField)],
                                       "searchForm" : form},
                                      )
    
def csvChosenModel(request, moduleName, modelName):
    """
        Returns a csv of the supplied query.
        """
    modelmodule = __import__('.'.join([moduleName,'models'])).models
    myModel = getattr(modelmodule,modelName)
    results = []
    fields = []
    if request.method == 'POST' :
        data = request.POST
    else:
        data = request.GET
    form = SearchForm(data=data,mymodel=myModel)

    if form.is_valid():  
        dfilters = {}
        for field in data :
            if data[field] :
                dfilters[field] = data[field]
        results = myModel.objects.filter(**dfilters).all()
        fields = [f.column for f in myModel._meta.fields ]      
        response = HttpResponse(content_type='text/csv')
        # if you want to download instead of display in browser         
        # response['Content-Disposition'] = 'attachment; filename='+modelName+'.csv'
        writer = csv.writer(response)
        writer.writerow(fields)
        for r in results:
            writer.writerow( [getattr(r,f) for f in fields if hasattr(r,f) ] )
    else:
        results = [ (x,form.errors[x]) for x in form.errors ]
        response = HttpResponse("\n".join(results), content_type="text/csv")

    return response


