# __BEGIN_LICENSE__
# Copyright (C) 2008-2013 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import sys
import re
import traceback
import json
import csv
import datetime
import calendar
from itertools import chain

from django.shortcuts import render_to_response, render
from django.http import HttpResponseNotAllowed, HttpResponse
from django.template import RequestContext
from django.db import connection, DatabaseError
from django.db.models import get_app, get_apps, get_models
from django.db.models.fields import DateTimeField, DateField, TimeField
from django.forms.models import ModelMultipleChoiceField, model_to_dict
from django import forms
from django.db.models import Model
from django.forms.formsets import formset_factory
from django.core.paginator import Paginator
from django.utils.html import escape

from xgds_data import settings
from xgds_data.introspection import modelFields
from xgds_data.models import getModelByName
from xgds_data.forms import QueryForm, SearchForm, AxesForm, SpecializedForm
from xgds_data.logging import recordRequest, recordList, log_and_render
from xgds_data.logconfig import logEnabled
if logEnabled():
    from xgds_data.models import ResponseLog
from xgds_data.search import makeFilters, sortFormula, countMatches, \
    divineWhereClause, sortThreshold

def index(request):
    return HttpResponse("Hello, world. You're at the xgds_data index.")

def hasModels(appName):
    return len(get_models(get_app(appName))) != 0

def getModelInfo(qualifiedName, model):
    return {
        'name': model.__name__,
        'qualifiedName': qualifiedName
    }

if (hasattr(settings, 'XGDS_DATA_SEARCH_SKIP_APP_PATTERNS')):
    SKIP_APP_REGEXES = [re.compile(_p) for _p in settings.XGDS_DATA_SEARCH_SKIP_APP_PATTERNS]

def isSkippedApp(appName):
    try:
        return any((r.match(appName) for r in SKIP_APP_REGEXES))
    except NameError:
        return (appName.find('django') > -1)

def searchModelsDefault():
    """
    Pick out some reasonable search models if none were explicitly listed
    """
    nestedModels = [get_models(app)
                    for app in get_apps()
                    if not isSkippedApp(app.__name__) and get_models(app)]
    return dict([(model.__name__, model) for model in list(chain(*nestedModels)) if not model._meta.abstract])

if (hasattr(settings, 'XGDS_DATA_SEARCH_MODELS')):
    SEARCH_MODELS = dict([(name, getModelByName(name))
                          for name in settings.XGDS_DATA_SEARCH_MODELS])
else:
    SEARCH_MODELS = searchModelsDefault()

MODELS_INFO = [getModelInfo(_qname, _model)
               for _qname, _model in SEARCH_MODELS.iteritems()]

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
    apps = [re.sub(r'\.models$', '', app) for app in apps]
    apps = [app for app in apps
            if (not isSkippedApp(app)) and hasModels(app)]
    return render(request,
                  'xgds_data/chooseSearchApp.html',
                  {'title': 'Search Apps',
                   'apps': apps})


def chooseSearchModel(request, moduleName):
    """
    List the models in the module, so they can be selected for search
    """
    app = get_app(moduleName)
    models = [m.__name__ for m in get_models(app) if not m._meta.abstract]

    return render(request, 'xgds_data/chooseSearchModel.html',
                  {'title': 'Search ' + moduleName,
                   'module': moduleName,
                   'models': sorted(models)}
                  )

def csvEncode(something):
    """
    csvlib can't deal with non-ascii unicode, thus, this function
    """
    if isinstance(something, unicode):
        return something.encode("ascii", errors='xmlcharrefreplace')
        # return something.encode("utf-8")
    else:
        return something

def formsetifyFieldName(i, fname):
    """
    Returns the field name for the ith form and given fname
    """
    return '-'.join(['form', str(i), fname])

def resolveTemplate(configName, myModel, defaultTemplate):
    """
    Figures out whether a specialized template exists, or if the default should be used
    """
    template = None
    config = getattr(settings, configName, None)
    if (config):
        for model in myModel.__mro__:
            if not template and issubclass(model, Model) and model != Model:
                template = config.get(model._meta.object_name, None)
    if template:
        return template
    else:
        return defaultTemplate

def searchSimilar(request, moduleName, modelName, pkid):
    """
    Launch point for finding more items like this one
    """
    reqlog = recordRequest(request)
    modelmodule = get_app(moduleName)
    myModel = getattr(modelmodule, modelName)
    myFields = modelFields(myModel)
    tmpFormClass = SpecializedForm(SearchForm, myModel)
    tmpFormSet = formset_factory(tmpFormClass, extra=0)
    debug = []
    data = request.REQUEST
    # me = myModel.objects.get(pk=data.get(myModel._meta.pk.name))
    #pkid = 1
    me = myModel.objects.get(pk=pkid)
    defaults = dict()
    aForm = tmpFormClass()
    medict = model_to_dict(me)

    for fld in medict.keys():
        op = fld + '_operator'
        f = aForm.fields.get(op, None)
        if f is None:
            continue

        if f.choices.count(('IN~', 'IN~')):
            defaults[op] = 'IN~'
        else:
            defaults[op] = '='

        if fld in aForm.fields:
            defaults[fld] = str(medict[fld])

        lo = fld + '_lo'
        if lo in aForm.fields:
            defaults[lo] = medict[fld]

        hi = fld + '_hi'
        if hi in aForm.fields:
            defaults[hi] = medict[fld]

    formset = tmpFormSet(initial=[defaults])
    resultCount = None
    datetimefields = []
    for x in myFields:
        if isinstance(x, DateTimeField):
            for y in [0, 1]:
                datetimefields.append(formsetifyFieldName(y, x.name))
    axesform = AxesForm(myFields, data)
    template = resolveTemplate('XGDS_DATA_SEARCH_TEMPLATES', myModel, 'xgds_data/searchChosenModel.html')
    return log_and_render(request, reqlog, template,
                          {'title': 'Search '+modelName,
                           'module': moduleName,
                           'model': modelName,
                           'debug':  debug,
                           'count': resultCount,
                           'datetimefields': datetimefields,
                           'formset': formset,
                           'axesform': axesform},
                          nolog = ['formset', 'axesform'])

def searchChosenModel(request, moduleName, modelName, expert=False):
    """
    Search over the fields of the selected model
    """
    starttime = datetime.datetime.now()
    reqlog = recordRequest(request)
    modelmodule = get_app(moduleName)
    myModel = getattr(modelmodule, modelName)
    myFields = modelFields(myModel)
    tmpFormClass = SpecializedForm(SearchForm, myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    debug = []
    data = request.REQUEST
    formCount = 1
    mode = data.get('mode', False)
    page = data.get('pageno', None)
    if page:
        picks = [int(p) for p in data.getlist('picks')]
    else:
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
    if (mode == 'csvhard'):
        soft = False
        mode = 'csv'

    if (mode == 'addform'):
        formCount = int(data['form-TOTAL_FORMS'])
        ## this is very strange, but the extra forms don't come up with the right defaults
        ## create a new form and read what the initial values should be
        blankForm = tmpFormClass()
        #newdata = data.copy()
        newdata = dict(data)
        for fname, field in blankForm.fields.iteritems():
            if isinstance(field, ModelMultipleChoiceField):
                val = [unicode(x.id) for x in field.initial]
                # FIX: does val need to be turned into a string somehow?
                newdata[formsetifyFieldName(formCount, fname)] = val
            elif ((not isinstance(field, forms.ChoiceField)) & (not field.initial)):
                newdata[formsetifyFieldName(formCount, fname)] = unicode('')
            else:
                newdata[formsetifyFieldName(formCount, fname)] = unicode(field.initial)
        newdata['form-TOTAL_FORMS'] = unicode(formCount  + 1 )
        formset = tmpFormSet(newdata)  # but passing data nullifies extra
    elif ((mode == 'query') or (mode == 'csv')):
        formCount = int(data['form-TOTAL_FORMS'])
        formset = tmpFormSet(data)
        if formset.is_valid():
            filters = makeFilters(formset, soft)
            query = myModel.objects.filter(filters)
            hardquery = myModel.objects.filter(makeFilters(formset, False))
            scorer = sortFormula(myModel, formset)
            if scorer:
                query = query.extra(select={'score': scorer}, order_by=['-score'])
            if (mode == 'csv'):
                results = query.all()
                if scorer:
                    limit = countMatches(myModel,
                                         scorer,
                                         divineWhereClause(myModel, filters, formset),
                                         sortThreshold())
                    results = results[0:limit]
                fnames = [f.column for f in myFields]
                response = HttpResponse(content_type='text/csv')
                # if you want to download instead of display in browser
                # response['Content-Disposition'] = 'attachment; filename='+modelName + '.csv'
                writer = csv.writer(response)
                writer.writerow(fnames)
                for r in results:
                    writer.writerow([csvEncode(getattr(r, f))
                                     for f in fnames if hasattr(r, f)])
                if logEnabled():
                    reslog = ResponseLog.objects.create(request=reqlog)
                    recordList(reslog, results)
                return response
            elif (mode == 'query'):
                if scorer:
                    ## resultCount = countApproxMatches(myModel, scorer, query.count(), sortThreshold())
                    resultCount = countMatches(myModel,
                                 scorer,
                                 divineWhereClause(myModel, filters, formset),
                                 sortThreshold())
                    hardCount = hardquery.count()
                    if resultCount < hardCount:
                        resultCount = hardCount
                    query = query[0:resultCount]
                else:
                    resultCount = query.count()
                    hardCount = resultCount
                resultsPages = Paginator(query, 10)
                resultsPage = resultsPages.page(page)
                results = resultsPages.page(page).object_list
                resultids = [getattr(r, myModel._meta.pk.name) for r in results]
        else:
            debug = formset.errors
    else:
        formset = tmpFormSet()

    datetimefields = []
    for x in myFields :
        if isinstance(x, DateTimeField):
            for y in range(0, formCount + 1):
                datetimefields.append(formsetifyFieldName(y, x.name))
    axesform = AxesForm(myFields, data)

    if (not axesform.fields.get('yaxis')):
        ## if yaxis is not defined, then we can't really plot
        axesform = None
    elif (data.get('xaxis') is None) or (data.get('xaxis') is None):
        ## lame, but Django doesn't appear to use the defined initial value when displaying as_hidden
        ## this will mess everything up
        ## thus, we force the initial values here.
        ## this should only be executed when the form is blank (i.e., initially)
        qd = {'xaxis': axesform.fields.get('xaxis').initial,
              'yaxis': axesform.fields.get('yaxis').initial,
              'series': axesform.fields.get('series').initial}
        qd.update(data)
        axesform = AxesForm(myFields, qd)
    template = resolveTemplate('XGDS_DATA_SEARCH_TEMPLATES', myModel, 'xgds_data/searchChosenModel.html')
    return log_and_render(request, reqlog, template,
                          {'title': 'Search '+ modelName,
                           'module': moduleName,
                           'model': modelName,
                           'debug' : debug,
                           'count' : resultCount,
                           'duration' : (datetime.datetime.now() - starttime).total_seconds(),
                           'expert' : expert,
                           'exactCount' : hardCount,
                           'datetimefields' : datetimefields,
                           'displayFields' : [ x for x in myFields if not x.primary_key ],
                           'formset' : formset,
                           'axesform' : axesform,
                           'page' : page,
                           'results': results,
                           'resultids': resultids,
                           'resultsPage': resultsPage,
                           'picks' : picks,
                           'checkable' : True,
                           },
                    nolog = ['formset', 'axesform', 'results', 'resultsids'],
                    listing = results)

def plotQueryResults(request, moduleName, modelName, start, end, soft=True):
    """
    Plot the results of a query
    """
    start = int(start)
    end = int(end)
    reqlog = recordRequest(request)
    modelmodule = __import__('.'.join([moduleName, 'models'])).models
    myModel = getattr(modelmodule, modelName)
    myFields = modelFields(myModel)
    tmpFormClass = SpecializedForm(SearchForm, myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    data = request.REQUEST
    soft = soft in (True, 'True')

    axesform = AxesForm(myFields, data)
    fieldDict = { x.name: x for x in myFields }
    timeFields = [fieldName
                  for fieldName, fieldVal in fieldDict.iteritems()
                  if isinstance(fieldVal, (DateField, TimeField))]

    formset = tmpFormSet(data)
    if formset.is_valid():
        ## a lot of this code mimics what is in searchChosenModel
        ## should figure out a way of centralizing instead of copying
        scorer = sortFormula(myModel, formset)
        filters = makeFilters(formset, soft)
        objs = myModel.objects.filter(filters)
        if scorer :
            objs = objs.extra(select={'score': scorer}, order_by = ['-score'])
            ##resultCount = countApproxMatches(myModel._meta.db_table, scorer, objs.count(), sortThreshold())
            resultCount = countMatches(myModel,
                                       scorer,
                                       divineWhereClause(myModel, filters, formset),
                                       sortThreshold())
        else:
            resultCount = objs.count()
        objs = objs[start:min(end, resultCount)]
        ##print(objs.query)
        ##plotdata = list(myModel.objects.filter(filters).values())
        ##pldata = [x.__str__() for x in myModel.objects.filter(filters)]
        ## objs = myModel.objects.filter(filters)[5:100]

        def megahandler(obj):
            if isinstance(obj, datetime.datetime):
                return calendar.timegm(obj.timetuple()) * 1000
            elif isinstance(obj, Model):
                return escape(str(obj))
            elif isinstance(obj, (int, long, float, complex)):
                return obj
            else:
                return escape(obj)

        plotdata = [{fld.name:megahandler(fld.value_from_object(x))
                     for fld in myFields}
                    for x in objs]
        pldata = [str(x) for x in objs]
        ##pldata = [str(x.denominator) for x in objs]

        ## the following code determines if there are any foreign keys that can be selected, and if so,
        ## replaces the corresponding values (which will be ids) with the string representation
        seriesChoices = dict(axesform.fields['series'].choices)

        def getRelated(modelField):
            return {getattr(x, x._meta.pk.name): escape(str(x))
                    for x in modelField.rel.to.objects.all()}

        seriesValues = {m.name: getRelated(m)
                        for m in myFields
                        if (m.rel is not None and
                            m.name in seriesChoices)}
        for x in plotdata:
            for k in seriesValues.keys():
                if x[k] is not None:
                    try:
                        x[k] = seriesValues[k][x[k]]
                    except:  # pylint: disable=W0702
                        x[k] = str(x[k])  # seriesValues[k][seriesValues[k].keys()[0]]

        debug = []
        #resultCount = myModel.objects.filter(filters).count()
        shownCount = len(pldata)
    else:
        debug = [(x, formset.errors[x]) for x in formset.errors]
        resultCount = None
        pldata = []
        plotdata = []
        objs = []

    def megahandler2(obj):
        if isinstance(obj, datetime.datetime):
            return calendar.timegm(obj.timetuple()) * 1000
        elif isinstance(obj, Model):
            return str(obj)
        else:
            return None

    template = resolveTemplate('XGDS_DATA_PLOT_TEMPLATES', myModel, 'xgds_data/plotQueryResults.html')
    return log_and_render(request, reqlog, template,
                          {'plotData' : json.dumps(plotdata, default=megahandler2),
                           'labels' : pldata,
                           'timeFields': json.dumps(timeFields),
                           'title': 'Plot ' + modelName,
                           'module': moduleName,
                           'model': modelName,
                           'pk' : myModel._meta.pk.name,
                           'start' : start,
                           'end' : end,
                           'debug' :  debug,
                           'count' : resultCount,
                           'showncount' : shownCount,
                           "formset" : formset,
                           'axesform' : axesform
                           },
                    nolog = ['plotData', 'labels', 'formset', 'axesform'],
                    listing = objs)

