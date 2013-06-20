# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import sys
import re
import traceback
import csv
import json

import time

from django.shortcuts import render_to_response, render
from django.http import HttpResponseNotAllowed, HttpResponseRedirect, HttpResponseForbidden, Http404, HttpResponse
from django.template import RequestContext
from django.core.paginator import Paginator
from django.db import connection, DatabaseError
from django.db.models import get_app, get_apps, get_models, Min, Max

from xgds_data.models import getModelByName
from xgds_data.forms import QueryForm, SearchForm, AxesForm
from xgds_data import settings
                
from inspect import isclass, getmembers, getmodule
from django.db.models import Q
from django.db.models.fields import DateTimeField, DateField, DecimalField, FloatField, IntegerField, TimeField
from django.forms.models import ModelMultipleChoiceField
from django.forms.fields import ChoiceField
from django import forms
from django.db.models import Model 
from django.forms.formsets import formset_factory
import datetime
import calendar

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
    app = get_app(moduleName)
    models = [m.__name__ for m in get_models(app) if not m._meta.abstract]

    return render(request,'xgds_data/chooseSearchModel.html', 
                  {'title': 'Search '+moduleName,
                   'module': moduleName,
                   'models' : sorted(models)}
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
    """
        Returns form class for the given model, so you don't have to pass the model to the constructor
        """
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
    """
        Returns the field name for the ith form and given fname
        """
    return '-'.join(['form',str(i),fname])

def makeFilters(formset):
    """
        Helper for searchChosenModel; figures out restrictions given a formset
        """
    filters = None
    ## forms are interpreted as internally conjunctive, externally disjunctive
    for form in formset:
        subfilter = Q()
        for field in form.cleaned_data :
            if form.cleaned_data[field] != None:
                clause  = None
                negate = False
                if field.endswith('_operator') :
                    pass
                elif (field.endswith('_lo') or field.endswith('_hi')):
                    base = field[:-3]
                    loval = form.cleaned_data[base+'_lo']
                    hival = form.cleaned_data[base+'_hi']                    
                    operator = form.cleaned_data[base+'_operator']
                    if (operator == 'IN~') :
                        ## this isn't a restriction, so ignore
                        pass
                    else :
                        negate = form.cleaned_data[base+'_operator'] == 'NOT IN'
                        if (loval != None and hival != None and field.endswith('_lo')) :
                            ## range query- handle on _lo to prevent from doing it twice
                            ## this aren't simple Q objects so don't set clause variable
                            if (negate) :
                                negate = False
                                subfilter &= Q(**{ base+'__lt' : loval }) | Q(**{ base+'__gt' : hival })
                            else :
                                subfilter &= Q(**{ base+'__gte' : loval }) & Q(**{ base+'__lte' : hival })
                        elif (loval != None) :
                            clause = Q(**{ base+'__gte' : loval })
                        elif (hival != None) :
                            clause = Q(**{ base+'__lte' : hival })          
                elif (isinstance(form[field].field,forms.ModelMultipleChoiceField)):
                    clause = Q(**{ field+'__in' : form.cleaned_data[field] })
                    negate = form.cleaned_data[field+'_operator'] == 'NOT IN'
                elif (isinstance(form[field].field,forms.ModelChoiceField)):
                    negate = form.cleaned_data[field+'_operator'] == '!='
                    clause = Q(**{ field+'__exact' : form.cleaned_data[field] })
                elif (isinstance(form[field].field,forms.ChoiceField)):
                    negate = form.cleaned_data[field+'_operator'] == '!='
                    if (form.cleaned_data[field]  == 'True') :
                        ## True values appear to be represented as numbers greater than 0
                        clause = Q(**{ field+'__gt' : 0 })
                    elif (form.cleaned_data[field]  == 'False') :
                        ## False values appear to be represented as 0
                        clause = Q(**{ field+'__exact' : 0 })
                else :
                    if form.cleaned_data[field] :
                        negate = form.cleaned_data[field+'_operator'] == '!='
                        clause = Q(**{ field+'__icontains' : form.cleaned_data[field] })
                if clause :
                    if negate :
                        subfilter &= ~clause
                    else :
                        subfilter &= clause
        if filters :
            filters |= subfilter  
        else :
            filters = subfilter 
    return filters
        
def scoreNumericOLD(field,val,minimum,maximum) :
    """
        provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
        """

    if (val == None) :
        return '1'  # same constant for everyone, so it factors out
    elif (val == 'min') :
        val = minimum
    elif (val == 'max') :
        val = maximum
    if (isinstance(val,list)) :
        lorange = val[0]
        hirange = val[1]
    else :
        lorange = val
        hirange = val       
        
    if (isinstance(lorange,datetime.datetime)) :
        lorange = time.mktime(lorange.timetuple())
    if (isinstance(hirange,datetime.datetime)) :
        hirange = time.mktime(hirange.timetuple())
    if (isinstance(minimum,datetime.datetime)) :
        minimum = time.mktime(minimum.timetuple())
    if (isinstance(maximum,datetime.datetime)) :
        maximum = time.mktime(maximum.timetuple())
            
    if ((lorange <= minimum) and (maximum <= hirange)) :
        return '1' 
    else :
        return "1-(greatest(least({1}-{0},{0}-{2}),0)/{3})".format(
                                                    field,lorange,hirange,max(0,lorange-minimum,maximum-hirange))

def baseScore(field,lorange,hirange) :
    """
        provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
        """
    timeConversion = False
    if (isinstance(lorange,datetime.datetime)) :
        timeConversion = True
        lorange = time.mktime(lorange.timetuple())
    if (isinstance(hirange,datetime.datetime)) :
        timeConversion = True
        hirange = time.mktime(hirange.timetuple())
    ## perhaps could swap lo, hi if lo > hi
    if (timeConversion) :
        field = 'UNIX_TIMESTAMP({0})'.format(field)
    
    if (lorange == hirange) :
        return "abs({0}-{1})".format(field,lorange)
    elif (lorange == 'min') :
        return "greatest(0,{0}-{1})".format(field,hirange)
    elif (hirange == 'max') :
        return "greatest(0,{1}-{0})".format(field,lorange)
    else :
        ##return "greatest(0,least({1}-{0},{0}-{2}))".format(field,lorange,hirange)
        return "greatest(0,{1}-{0},{0}-{2})".format(field,lorange,hirange)

def medianEval(table,expression,size) :
    """
        Quick mysql-y way of estimating the median from a sample; not very Django-y
        """
    sampleSize = min(size,1000)
    sql = 'select {1} as score from {0} JOIN ({3}) AS r2 USING (id) order by score limit {2},1;'.format(
            table,expression,sampleSize/2,
            '(SELECT CEIL(RAND() * (SELECT MAX(id) FROM {0})) AS id from {0} limit {1})'.format(table,sampleSize))
    cursor = connection.cursor()
    cursor.execute(sql)
    return cursor.fetchone()[0]

def scoreNumeric(model,field,lorange,hirange,tableSize) :
    """
        provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
        """   
    return "1 /(1 + {0}/{1})".format(baseScore(field,lorange,hirange),
                        medianEval(model._meta.db_table,baseScore(field,lorange,hirange),tableSize)) 
    #return "1-(1 + {1}) /(2 + 2 * {0})".format(baseScore(field,lorange,hirange),
    #                    medianEval(model._meta.db_table,baseScore(field,lorange,hirange),tableSize)) 

def sortFormula(model, formset, query):
    """
        Helper for searchChosenModel; comes up with a formula for ordering the results
        """

    desiderata = dict()
    ## forms are interpreted as internally conjunctive, externally disjunctive
    for form in formset:
        for field in form.cleaned_data :
            if form.cleaned_data[field] != None:
                if (field.endswith('_operator') and (form.cleaned_data[field] == 'IN~')) :
                    base = field[:-9]
                    operator = form.cleaned_data[base+'_operator']
                    if (operator == 'IN~') :
                        loval = form.cleaned_data[base+'_lo']
                        hival = form.cleaned_data[base+'_hi']
                        if ((loval == None) or (loval == 'None')) :
                            loval = 'min'
                        if ((hival == None) or (hival == 'None')) :
                            hival = 'max'
                        if ((loval != 'min') or (hival != 'max')) :
                            desiderata[base] = [loval,hival]

    if (len(desiderata) > 0) :
        tableSize = model.objects.count()
        
        formula = ' + '.join([scoreNumeric(model,b,desiderata[b][0],desiderata[b][1],tableSize) for b in desiderata.keys()])
        return formula
    else :
        return None

                    
def searchChosenModel(request, moduleName, modelName):
    """
        Search over the fields of the selected model
        """
    modelmodule = get_app(moduleName)
    myModel = getattr(modelmodule,modelName)
    modelFields = myModel._meta.fields
    tmpFormClass = specializedSearchForm(myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    debug = []
    if request.method == 'POST' :
        data = request.POST;
    else:
        data = request.GET
    formCount = 1
    mode = data.get('mode',False)
    filters = None
    if (mode == 'addform') :
        formCount = int(data['form-TOTAL_FORMS'])
        ## this is very strange, but the extra forms don't come up with the right defaults
        ## create a new form and read what the initial values should be
        blankForm = tmpFormClass()      
        newdata = data.copy()
        for fname, field in blankForm.fields.iteritems() :
            if isinstance(field,ModelMultipleChoiceField) :
                val = [ unicode(x.id) for x in field.initial ]
                newdata.setlist(formsetifyFieldName(formCount,fname),val)
            elif ((not isinstance(field,ChoiceField)) & (not field.initial)) :
                newdata[formsetifyFieldName(formCount,fname)] = unicode('')
            else :
                newdata[formsetifyFieldName(formCount,fname)] = unicode(field.initial)
        newdata['form-TOTAL_FORMS'] = unicode(formCount  + 1 ) 
        formset = tmpFormSet(newdata)  # but passing data nullifies extra
    elif ((mode == 'query') or (mode == 'csv')) :
        formCount = int(data['form-TOTAL_FORMS'])
        formset = tmpFormSet(data)
        if formset.is_valid():  
            filters = makeFilters(formset)      
        else:
            debug = formset.errors  
    else:
        formset = tmpFormSet()
        
    if ((mode == 'csv') and formset.is_valid()): 
        query = myModel.objects.filter(filters)
        scorer = sortFormula(myModel, formset,query)
        if (scorer) :
            query = query.extra(select={'score': scorer}, order_by = ['-score'])
        results = query.all()
        fnames = [f.column for f in modelFields ]      
        response = HttpResponse(content_type='text/csv')
        # if you want to download instead of display in browser  
        # response['Content-Disposition'] = 'attachment; filename='+modelName+'.csv'
        writer = csv.writer(response)
        writer.writerow(fnames)
        for r in results:
            writer.writerow( [csvEncode(getattr(r,f)) for f in fnames if hasattr(r,f) ] )
        return response
    else :
        if ((mode == 'query') and formset.is_valid()):  
            resultCount = myModel.objects.filter(filters).count()
        else :
            resultCount = None
        datetimefields = []
        for x in modelFields :
            if isinstance(x,DateTimeField) :
                for y in range(0,formCount+1) :
                    datetimefields.append(formsetifyFieldName(y,x.name))
        axesform = AxesForm(modelFields,data)       
            
        if (not axesform.fields.get('yaxis')) :
            ## if yaxis is not defined, then we can't really plot
            axesform = None
        elif ((data.get('xaxis') == None) or (data.get('xaxis') == None)) :
            ## lame, but Django doesn't use the defined initial value when displaying as_hidden
            ## this will mess everything up
            ## thus, we force the initial values here.
            ## this should only be executed when the form is blank (i.e., initially)
            qd = data.copy()
            qd.setdefault('xaxis',axesform.fields.get('xaxis').initial)
            qd.setdefault('yaxis',axesform.fields.get('yaxis').initial)
            qd.setdefault('series',axesform.fields.get('series').initial)
            axesform = AxesForm(modelFields,qd)

        return render(request,'xgds_data/searchChosenModel.html', 
                              {'title': 'Search '+modelName,
                               'module': moduleName,
                               'model': modelName,
                               'debug' :  debug,
                               'count' : resultCount,
#                               'resultsPage': resultsPage,
                               'datetimefields' : datetimefields,
                               "formset" : formset,
                               'axesform' : axesform},
                              )

def plotQueryResults(request, moduleName, modelName, start, end):
    """
        Plot the results of a query
        """
    modelmodule = __import__('.'.join([moduleName,'models'])).models
    myModel = getattr(modelmodule,modelName)
    modelFields = myModel._meta.fields
    tmpFormClass = specializedSearchForm(myModel)
    tmpFormSet = formset_factory(tmpFormClass)   
    if request.method == 'POST' :
        data = request.POST;
    else:
        data = request.GET
    
    axesform = AxesForm(modelFields,data);
    timeFields = []
    fieldDict = dict([ (x.name,x) for x in modelFields ])
    for f in fieldDict.keys() :
        if (isinstance(fieldDict[f],DateField) or isinstance(fieldDict[f],TimeField)) :
            timeFields.append(f)
    
    formset = tmpFormSet(data)
    if formset.is_valid():  
        filters = makeFilters(formset)
        objs = myModel.objects.filter(filters)
        scorer = sortFormula(myModel,formset,objs)
        if (scorer) :
            objs = objs.extra(select={'score': scorer}, order_by = ['-score'])
        objs = objs[start:end]
        ##print(objs.query)
        ##plotdata = list(myModel.objects.filter(filters).values())
        ##pldata = [x.__str__() for x in myModel.objects.filter(filters)]
        ## objs = myModel.objects.filter(filters)[5:100]
        plotdata = [ dict([(fld.column,fld.value_from_object(x)) for fld in modelFields ]) for x in objs]
        pldata = [x.__str__() for x in objs]
        ##pldata = [x.denominator.__str__() for x in objs]
        
        ## the following code determines if there are any foreign keys that can be selected, and if so,
        ## replaces the corresponding values (which will be ids) with the string representation
        seriesChoices = dict(axesform.fields['series'].choices)
        seriesValues = dict([ (m.column, dict([ (getattr(x,x._meta.pk.name),x.__str__()) 
                                         for x in m.rel.to.objects.all() ]) ) 
                       for m in modelFields if (m.rel != None) and (seriesChoices.has_key(m.column)) ])

        for x in plotdata :
            for k in seriesValues.keys() :
                if (x[k] != None) :
                    x[k] = seriesValues[k][x[k]]
        
        debug = []
        resultCount = myModel.objects.filter(filters).count()     
        shownCount = len(pldata) 
    else:
        debug = [ (x,formset.errors[x]) for x in formset.errors ]
        resultCount = None
        pldata = []
        plotdata = []

    megahandler = lambda obj: calendar.timegm(obj.timetuple()) * 1000 \
            if isinstance(obj, datetime.datetime) else obj.__str__() if isinstance(obj,Model) else None
    return render(request,'xgds_data/plotQueryResults.html', 
                          {'plotData': json.dumps(plotdata,default=megahandler),
                           'labels': pldata,
                           'timeFields': json.dumps(timeFields),
                           'title': 'Plot '+modelName,
                           'module': moduleName,
                           'model': modelName,
                           'start' : start,
                           'end' : end,
                           'debug' :  debug,
                           'count' : resultCount,
                           'showncount' : shownCount,
                           "formset" : formset,
                           'axesform' : axesform},
                          )


SKIP_APP_REGEXES = [re.compile(p) for p in settings.XGDS_DATA_SEARCH_SKIP_APP_PATTERNS]


def isSkippedApp(appName):
    return any((r.match(appName) for r in SKIP_APP_REGEXES))


def hasModels(appName):
    return len(get_models(get_app(appName))) != 0


def chooseSearchApp(request):
    apps = [app.__name__ for app in get_apps()]
    apps = [re.sub('\.models$', '', app) for app in apps]
    apps = [app for app in apps
            if (not isSkippedApp(app)) and hasModels(app)]
    return render(request,
                  'xgds_data/chooseSearchApp.html',
                  {'apps': apps})
