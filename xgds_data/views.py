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
from django.db import connection, DatabaseError
from django.db.models import get_app, get_apps, get_models, Min, Max

from xgds_data.models import getModelByName
from xgds_data.forms import QueryForm, SearchForm, AxesForm
from xgds_data import settings
from xgds_data.models import logEnabled
if logEnabled() :
    from xgds_data.models import RequestLog, RequestArgument, ResponseLog, ResponseArgument, ResponseList
                
from django.db.models import Q
from django.db.models.fields import DateTimeField, DateField, PositiveIntegerField, PositiveSmallIntegerField, TimeField, related
from django.db.models.fields.related import ForeignKey
from django.forms.models import ModelMultipleChoiceField, model_to_dict
import django.forms.fields
#from django.forms.fields import ChoiceField
#from django.forms.fields import DateTimeField
from django import forms
from django.db.models import Model 
from django.forms.formsets import formset_factory
import datetime
import calendar
from math import pow,floor,log10,log

from itertools import chain
from django.core.paginator import Paginator
from django.utils.html import escape

def index(request):
    return HttpResponse("Hello, world. You're at the xgds_data index.")

def hasModels(appName):
    return len(get_models(get_app(appName))) != 0

def getModelInfo(qualifiedName, model):
    return {
        'name': model.__name__,
        'qualifiedName': qualifiedName
    }

if (hasattr(settings, 'XGDS_DATA_SEARCH_SKIP_APP_PATTERNS')) :
    SKIP_APP_REGEXES = [re.compile(p) for p in settings.XGDS_DATA_SEARCH_SKIP_APP_PATTERNS]
    
def isSkippedApp(appName):
    try :
        return any((r.match(appName) for r in SKIP_APP_REGEXES))
    except NameError:
        return (appName.find('django') > -1)
    
def searchModelsDefault():
    """
        Pick out some reasonable search models if none were explicitly listed
        """
    nestedModels = [get_models(app) for app in get_apps() 
              if not isSkippedApp(app.__name__) and len(get_models(app)) != 0]
    return dict([(model.__name__, model) for model in list(chain(*nestedModels)) if not model._meta.abstract ])
    
if (hasattr(settings, 'XGDS_DATA_SEARCH_MODELS')) :
    SEARCH_MODELS = dict([(name, getModelByName(name))
                          for name in settings.XGDS_DATA_SEARCH_MODELS])
else :
    SEARCH_MODELS = searchModelsDefault()

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

def chooseSearchApp(request):
    apps = [app.__name__ for app in get_apps()]
    apps = [re.sub('\.models$', '', app) for app in apps]
    apps = [app for app in apps
            if (not isSkippedApp(app)) and hasModels(app)]
    return render(request,
                  'xgds_data/chooseSearchApp.html',
                  {'title': 'Search Apps','apps': apps})



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

def divineWhereClause(myModel,filters,formset):
    """
        Pulls out the where clause and quotes the likely literals. Probably really brittle and should be replaced
        """
    post = str(myModel.objects.filter(filters).query)
    wherestart = post.find(' WHERE ')
    if (wherestart > -1) :
        newwhere = ' WHERE '
        for seg in re.compile("( [AO][NR]D? )").split(post[(wherestart+7):]) :
            eqpos = seg.find('= ')
            if (eqpos > -1) :
                quotable = seg.rstrip(') ')[(eqpos+1):].strip()
                quotepos = seg.find(quotable)
                newseg = seg[:quotepos]+'"'+quotable+'"'+seg[(quotepos+len(quotable)):]
            else :
                newseg = seg
            newwhere = newwhere + newseg
    else :
        newwhere = None
        
    return newwhere


def walkQ(qstmt):
    """
        A somewhat aborted attempt to piece together the corresponding sql from a Q object
        """
    if (isinstance(qstmt,Q)) :
        con = ' '+qstmt.connector+' '
        return '('+con.join([walkQ(x) for x in qstmt.children])+')'
    elif (isinstance(qstmt,tuple)) :
        subjpred,obj = qstmt
        doubleunderscorepos = subjpred.rfind('__')
        if (doubleunderscorepos) :
            subj = subjpred[:(doubleunderscorepos)]
            pred = subjpred[(doubleunderscorepos+2):]
            if (pred == 'lt') :
                pred = '<'
            elif (pred == 'gt') :
                pred = '>'
            elif (pred == 'gte') :
                pred = '>='
            elif (pred == 'lte') :
                pred = '<='
            elif (pred == 'in') :
                pred = 'IN'
            elif (pred == 'exact') :
                pred = '='
            elif (pred == 'icontains') :
                pred = 'ILIKE'
            if (not isinstance(obj, (int, long, float, complex))) :
                obj = '"' + str(obj) + '"'
            return '(' + ' '.join([subj,pred,str(obj)]) + ')'
        else :
            print("Cannot parse Q statement: "+str(qstmt))
    else :
        print("Encountered unexpected type"+qstmt.__class__)
        return '1 != 1'
    
def makeFilters(formset,soft=True):
    """
        Helper for searchChosenModel; figures out restrictions given a formset
        """
    filters = None
    ##if (threshold == 1) :
    ##    filters = None
    ##else :
    ##    filters = Q(**{ 'score__gte' : threshold } )
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
                    if ((operator == 'IN~') and soft) :
                        ## this isn't a restriction, so ignore
                        pass
                    else :
                        negate = form.cleaned_data[base+'_operator'] == 'NOT IN'
                        if (loval != None and hival != None) :
                            if (field.endswith('_lo')) :
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

def randomSample(table,expression,size,offset = None, limit = None) :
    """
        Selects a random set of records, assuming even distibution of ids; not very Django-y
        """
    randselect = '(SELECT CEIL(RAND() * (SELECT MAX(id) FROM {0})) AS id from {0} limit {1})'.format(table,size)
    if ((offset == None) or (limit == None)) :
        sql = 'select {1} as score from {0} JOIN ({2}) AS r2 USING (id) order by score;'.format(
            table,expression,randselect)
    else :
        sql = 'select {1} as score from {0} JOIN ({2}) AS r2 USING (id) order by score limit {3},{4};'.format(
            table,expression,randselect,offset,limit )
    cursor = connection.cursor()
    cursor.execute(sql)
    return cursor.fetchall()

def countMatches(table,expression,where,threshold):
    """
        Get the full count of records matching the restriction; can be slow
        """
    cursor = connection.cursor()
    if (where) :
        sql = 'select sum({1} >= {3}) from {0} {2};'.format(table,expression,where,threshold)
    else :
        sql = 'select sum({1} >= {2}) from {0};'.format(table,expression,threshold) 
    cursor.execute(sql)
    return cursor.fetchone()[0]

def countApproxMatches(table,scorer,maxSize,threshold):
    """
        Take a guess as to how many records match by examining a random sample
        """
    cpass = 0.0
    sample = randomSample(table,scorer,10000)
    for x in sample :
        if (x[0] >= threshold) :
            cpass = cpass + 1
    ##query = query[0:round(maxSize*cpass/len(sample))]
    resultCount = maxSize*cpass/len(sample)
    ## make it look approximate
    if (resultCount > 10) :
        resultCount = int(round(resultCount/pow(10,floor(log10(resultCount)))) 
                          * pow(10,floor(log10(resultCount)))) 
    elif (resultCount > 0) :
        resultCount = 10
    return resultCount
    
def medianEval(table,expression,size) :
    """
        Quick mysql-y way of estimating the median from a sample
        """
    sampleSize = min(size,1000)
    result = ()
    while (len(result) == 0) :
        result = randomSample(table,expression,sampleSize,sampleSize/2,1)
    return result[0][0]

def scoreNumeric(model,field,lorange,hirange,tableSize) :
    """
        provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
        """   
    ## Yuk ... need to convert if field is unsigned
    unsigned = False
    for f in model._meta.fields :
        if ((f.attname == field) and (isinstance(f,PositiveIntegerField) or 
                                      isinstance(f,PositiveSmallIntegerField))) :
            unsigned = True
    ## Add table designation to properly resolve a field name that has another SQL interpretation
    ## (for instance, a field name 'long')
    field = model._meta.db_table + '.' + field
    if (unsigned) :
        field = "cast({0} as SIGNED)".format(field)
    median = medianEval(model._meta.db_table,baseScore(field,lorange,hirange),tableSize)
    if (median == None) :
        return '1'
    elif (median == 0) :
        ## would get divide by zero with standard formula below
        ## defining 0/x == 0 always, limit of standard formula leads to special case for 0, below.
        return "({0} = {1})".format(baseScore(field,lorange,hirange),median) 
    else :
        return "1 /(1 + {0}/{1})".format(baseScore(field,lorange,hirange),median) 
    #return "1-(1 + {1}) /(2 + 2 * {0})".format(baseScore(field,lorange,hirange),
    #                    medianEval(model._meta.db_table,baseScore(field,lorange,hirange),tableSize)) 

def desiredRanges(model, formset):
    """
        Pulls out the approximate (soft) constraints from the form
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
    return desiderata;

def sortFormula(model, formset) :
    """
        Helper for searchChosenModel; comes up with a formula for ordering the results
        """
    desiderata = desiredRanges(model, formset)
    if (len(desiderata) > 0) :
        tableSize = model.objects.count()
        formula = ' + '.join([scoreNumeric(model,b,desiderata[b][0],desiderata[b][1],tableSize) for b in desiderata.keys()])
        return '({0})/{1} '.format(formula,len(desiderata))  # scale to have a max of 1
    else :
        return None

def sortThreshold() :
    """
        Guess on a good threshold to cutoff the search results
        """
    ## rather arbitrary cutoff, which would return 30% of results if scores are uniform
    return 0.7
    
def recordRequest(request):
    """
        Logs the request in the database
        """
    if logEnabled() :
        data = request.REQUEST
        reqlog = RequestLog.create(request)
        reqlog.save()
        for key in data :
            arg = RequestArgument.objects.create(request=reqlog,name=key,value=data.get(key))
            arg.save()
        return reqlog
    else :
        return None
                      
def recordList(reslog,results) :
    """
        Logs a ranked list of results
        """
    if logEnabled() :
        if (len(results) > 0) :
            ranks = range(1,min(201,len(results)))
            ranks.extend([(2**p) for p in range(8,1+int(floor(log(len(results),2))))])
            ranks.append(len(results))
            items = [ ResponseList(response = reslog, rank = r, fclass = str(results[r-1].__class__), fid = results[r-1].id ) \
                     for r in ranks ]
            ResponseList.objects.bulk_create(items)

def log_and_render(request, reqlog, template, rendargs, nolog = [], listing = None):
    """
        Logs the response in the database and returns the rendered page
        """
    if logEnabled() :
        reslog = ResponseLog.objects.create(request = reqlog, template = template)
        for key in rendargs :
            if (nolog.count(key) == 0) :
                ResponseArgument.objects.create(response=reslog,name=key,value=rendargs.get(key).__str__()[:1024])
        if (listing) :
            recordList(reslog,listing)
    return render(request,template,rendargs)

def searchSimilar(request, moduleName, modelName):
    """
        Launch point for finding more items like this one
        """
    reqlog = recordRequest(request)
    modelmodule = get_app(moduleName)
    myModel = getattr(modelmodule,modelName)
    modelFields = myModel._meta.fields
    tmpFormClass = specializedSearchForm(myModel)
    tmpFormSet = formset_factory(tmpFormClass, extra=0)
    debug = []
    data = request.REQUEST
    me = myModel.objects.get(pk=data.get(myModel._meta.pk.attname))
    defaults = dict()
    aForm = tmpFormClass()
    medict = model_to_dict(me)
    
    for fld in medict.keys() :
#        if ((aForm.fields.has_key(fld+'_operator')) and (aForm.fields[fld+'_operator'].choices.count(('IN~', 'IN~')))) :
        if (aForm.fields.has_key(fld+'_operator')) :
            if (aForm.fields[fld+'_operator'].choices.count(('IN~', 'IN~'))) :
                defaults[fld+'_operator'] = 'IN~'
            else :
                defaults[fld+'_operator'] = '='
            if (aForm.fields.has_key(fld)) :
                defaults[fld] = str(medict[fld])
            if (aForm.fields.has_key(fld+'_lo')) :
                defaults[fld+'_lo'] = medict[fld]
            if (aForm.fields.has_key(fld+'_hi')) :
                defaults[fld+'_hi'] = medict[fld]
    
    formset = tmpFormSet(initial=[defaults])
    resultCount = None
    datetimefields = []
    for x in modelFields :
        if isinstance(x,DateTimeField) :
            for y in [0,1] :
                datetimefields.append(formsetifyFieldName(y,x.name))
    axesform = AxesForm(modelFields,data)
    template = 'xgds_data/searchChosenModel.html'
    if (hasattr(settings, 'XGDS_DATA_SEARCH_TEMPLATES')) :
        template = settings.XGDS_DATA_SEARCH_TEMPLATES.get(modelName,template)
    
    return log_and_render(request,reqlog,template, 
                      {'title': 'Search '+modelName,
                       'module': moduleName,
                       'model': modelName,
                       'debug' :  debug,
                       'count' : resultCount,
                       'datetimefields' : datetimefields,
                       'formset' : formset,
                       'axesform' : axesform},
                      nolog = ['formset','axesform'])
    
def searchChosenModel(request, moduleName, modelName, expert=False):
    """
        Search over the fields of the selected model
        """
    reqlog = recordRequest(request)
    modelmodule = get_app(moduleName)
    myModel = getattr(modelmodule,modelName)
    modelFields = myModel._meta.fields
    tmpFormClass = specializedSearchForm(myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    debug = []
    data = request.REQUEST
    formCount = 1
    mode = data.get('mode',False)
    page = data.get('pageno',None)
    if page :
        picks = [int(p) for p in data.getlist('picks')]
    else :
        page = 1
        picks = []
    results = None
    resultids = None
    resultsPage = None
    filters = None
    resultCount = None
    hardCount = None
    soft = True
    #expert = (soft != None) and (soft == 'True')
    if (mode == 'csvhard') :
        soft = False
        mode = 'csv'

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
            elif ((not isinstance(field,forms.ChoiceField)) & (not field.initial)) :
                newdata[formsetifyFieldName(formCount,fname)] = unicode('')
            else :
                newdata[formsetifyFieldName(formCount,fname)] = unicode(field.initial)
        newdata['form-TOTAL_FORMS'] = unicode(formCount  + 1 ) 
        formset = tmpFormSet(newdata)  # but passing data nullifies extra
    elif ((mode == 'query') or (mode == 'csv')) :
        formCount = int(data['form-TOTAL_FORMS'])
        formset = tmpFormSet(data)
        if formset.is_valid():              
            filters = makeFilters(formset,soft)
            query = myModel.objects.filter(filters)
            hardquery = myModel.objects.filter(makeFilters(formset,False))
            scorer = sortFormula(myModel, formset)
            if (scorer) :
                query = query.extra(select={'score': scorer}, order_by = ['-score'])
            if (mode == 'csv'):                
                results = query.all()
                if (scorer) :
                    limit = countMatches(myModel._meta.db_table,
                                 scorer,
                                 divineWhereClause(myModel,filters,formset),
                                 sortThreshold())
                    results = results[0:limit]
                fnames = [f.column for f in modelFields ]      
                response = HttpResponse(content_type='text/csv')
                # if you want to download instead of display in browser  
                # response['Content-Disposition'] = 'attachment; filename='+modelName+'.csv'
                writer = csv.writer(response)
                writer.writerow(fnames)
                for r in results:
                    writer.writerow( [csvEncode(getattr(r,f)) for f in fnames if hasattr(r,f) ] )
                if logEnabled() :
                    reslog = ResponseLog.objects.create(request = reqlog)
                    recordList(reslog,results)
                return response
            elif (mode == 'query'):  
                if (scorer) :
                    resultCount = countApproxMatches(myModel._meta.db_table,scorer,query.count(),sortThreshold())
                    hardCount = hardquery.count() 
                    if (resultCount < hardCount) :
                        resultCount = hardCount
                else :
                    resultCount = query.count() 
                    hardCount = resultCount    
                resultsPages = Paginator(query, 30)
                resultsPage = resultsPages.page(page) 
                results = resultsPages.page(page).object_list
                resultids = [getattr(r,myModel._meta.pk.name) for r in results]
        else:
            debug = formset.errors
    else:
        formset = tmpFormSet()
                
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
        ## lame, but Django doesn't appear to use the defined initial value when displaying as_hidden
        ## this will mess everything up
        ## thus, we force the initial values here.
        ## this should only be executed when the form is blank (i.e., initially)
        qd = {'xaxis' : axesform.fields.get('xaxis').initial,
              'yaxis' : axesform.fields.get('yaxis').initial,
              'series' : axesform.fields.get('series').initial}
        qd.update(data)
        axesform = AxesForm(modelFields,qd)
    template = 'xgds_data/searchChosenModel.html'
    if (hasattr(settings, 'XGDS_DATA_SEARCH_TEMPLATES')) :
        template = settings.XGDS_DATA_SEARCH_TEMPLATES.get(modelName,template)
    return log_and_render(request, reqlog, template,
                   {'title': 'Search '+modelName,
                           'module': moduleName,
                           'model': modelName,
                           'debug' : debug,
                           'count' : resultCount,
                           'expert' : expert,
                           'exactCount' : hardCount,
                           'datetimefields' : datetimefields,
                           'formset' : formset,
                           'axesform' : axesform,
                           'page' : page,
                           'results': results,
                           'resultids': resultids,
                           'resultsPage': resultsPage,
                           'picks' : picks,
                           },
                    nolog = ['formset','axesform'])

def plotQueryResults(request, moduleName, modelName, start, end, soft=True):
    """
        Plot the results of a query
        """
    start = int(start)
    end = int(end)
    reqlog = recordRequest(request)
    modelmodule = __import__('.'.join([moduleName,'models'])).models
    myModel = getattr(modelmodule,modelName)
    modelFields = myModel._meta.fields
    tmpFormClass = specializedSearchForm(myModel)
    tmpFormSet = formset_factory(tmpFormClass)   
    data = request.REQUEST
    soft = (soft == True) or (soft == 'True')
    
    axesform = AxesForm(modelFields,data);
    timeFields = []
    fieldDict = dict([ (x.name,x) for x in modelFields ])
    for f in fieldDict.keys() :
        if (isinstance(fieldDict[f],DateField) or isinstance(fieldDict[f],TimeField)) :
            timeFields.append(f)
    
    formset = tmpFormSet(data)
    if formset.is_valid():  
        ## a lot of this code mimics what is in searchChosenModel
        ## should figure out a way of centralizing instead of copying
        scorer = sortFormula(myModel,formset)
        filters = makeFilters(formset,soft)
        objs = myModel.objects.filter(filters)
        if (scorer) :
            objs = objs.extra(select={'score': scorer}, order_by = ['-score'])
            ##resultCount = countApproxMatches(myModel._meta.db_table,scorer,objs.count(),sortThreshold())
            resultCount = countMatches(myModel._meta.db_table,
                                                     scorer,
                                                     divineWhereClause(myModel,filters,formset),
                                                     sortThreshold())
        else :
            resultCount = objs.count()
        objs = objs[start:min(end,resultCount)]
        ##print(objs.query)
        ##plotdata = list(myModel.objects.filter(filters).values())
        ##pldata = [x.__str__() for x in myModel.objects.filter(filters)]
        ## objs = myModel.objects.filter(filters)[5:100]
        megahandler = lambda obj: calendar.timegm(obj.timetuple()) * 1000 if isinstance(obj, datetime.datetime) \
            else escape(obj.__str__()) if isinstance(obj,Model) \
            else obj if isinstance(obj, (int, long, float, complex)) \
            else escape(obj)
        plotdata = [ dict([(fld.verbose_name,megahandler(fld.value_from_object(x))) for fld in modelFields ]) 
                    for x in objs]
        pldata = [x.__str__() for x in objs]
        ##pldata = [x.denominator.__str__() for x in objs]
        
        ## the following code determines if there are any foreign keys that can be selected, and if so,
        ## replaces the corresponding values (which will be ids) with the string representation
        seriesChoices = dict(axesform.fields['series'].choices)
        seriesValues = dict([ (m.verbose_name, dict([ (getattr(x,x._meta.pk.name),escape(x.__str__())) 
                                         for x in m.rel.to.objects.all() ]) ) 
                       for m in modelFields if (m.rel != None) and (seriesChoices.has_key(m.name)) ])
        for x in plotdata :
            for k in seriesValues.keys() :
                if (x[k] != None) :
                    try :
                        x[k] = seriesValues[k][x[k]]
                    except :
                        x[k] = str(x[k]) ##seriesValues[k][seriesValues[k].keys()[0]]
        
        debug = []
        #resultCount = myModel.objects.filter(filters).count()     
        shownCount = len(pldata) 
    else:
        debug = [ (x,formset.errors[x]) for x in formset.errors ]
        resultCount = None
        pldata = []
        plotdata = []
        objs = []

    megahandler = lambda obj: calendar.timegm(obj.timetuple()) * 1000 \
            if isinstance(obj, datetime.datetime) else obj.__str__() if isinstance(obj,Model) else None
    return log_and_render(request, reqlog, 'xgds_data/plotQueryResults.html',
                   {'plotData' : json.dumps(plotdata,default=megahandler),
                    'labels' : pldata,
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
                    nolog = ['plotData','labels','formset','axesform'],
                    listing = objs)

