# __BEGIN_LICENSE__
#Copyright (c) 2015, United States Government, as represented by the 
#Administrator of the National Aeronautics and Space Administration. 
#All rights reserved.
#
#The xGDS platform is licensed under the Apache License, Version 2.0 
#(the "License"); you may not use this file except in compliance with the License. 
#You may obtain a copy of the License at 
#http://www.apache.org/licenses/LICENSE-2.0.
#
#Unless required by applicable law or agreed to in writing, software distributed 
#under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR 
#CONDITIONS OF ANY KIND, either express or implied. See the License for the 
#specific language governing permissions and limitations under the License.
# __END_LICENSE__

import sys
import re
import traceback
import json
import csv
import datetime
import calendar
import StringIO
from itertools import chain

import pytz

from django.shortcuts import render_to_response, render
from django.http import HttpResponseNotAllowed, HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.template import RequestContext
from django.db import connection, DatabaseError
from django.db import models
from django.db.models import get_app, get_apps, get_models, ManyToManyField
from django.db.models.fields import DateTimeField, DateField, TimeField, related
from django.forms.models import ModelMultipleChoiceField, model_to_dict
from django import forms
from django.db.models import Model
from django.forms.formsets import formset_factory
from django.utils.html import escape
from django.contrib.auth.models import User

try:
    from geocamUtil.loader import getModelByName
    GEOCAMUTIL_FOUND = True
except ImportError:
    GEOCAMUTIL_FOUND = False

from xgds_data import settings
from xgds_data.introspection import (modelFields, maskField, isAbstract, 
                                     resolveModel, ordinalField,
                                     pk, pkValue, verbose_name, settingsForModel, 
                                     modelName, moduleName, fullid)
from xgds_data.forms import QueryForm, SearchForm, EditForm, AxesForm, SpecializedForm
from xgds_data.models import Collection, GenericLink
from xgds_data.dlogging import recordRequest, recordList, log_and_render
from xgds_data.logconfig import logEnabled
from xgds_data.search import getMatches, pageLimits, retrieve
from xgds_data.utils import total_seconds
from xgds_data.templatetags import xgds_data_extras

from django.core.urlresolvers import resolve
from django.utils.datastructures import MergeDict
from django.http import QueryDict
try:
    from django.forms.utils import ErrorList, ErrorDict
except ImportError:
    pass   

if logEnabled():
    from xgds_data.models import RequestLog, RequestArgument, ResponseLog, HttpRequestReplay


def formsetToQD(formset):
    return [form.cleaned_data for form in formset]


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
    return dict([(model.__name__, model) for model in list(chain(*nestedModels)) if not isAbstract(model)])

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


def searchModel(request, searchModelName):
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])

    model = SEARCH_MODELS[searchModelName]
    tableName = model._meta.db_table
    modelInfo = getModelInfo(searchModelName, model)

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
                     + '<span style="color: blue;">%s</span>' % userQuery
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


def chooseModel(request, moduleName, title, action, urlName):
    """
    List the models in the module, so they can be selected
    """
    app = get_app(moduleName)
    models = dict([(verbose_name(m), m) for m in get_models(app) if not isAbstract(m)])
    ordered_names = sorted(models.keys())

    return render(request, 'xgds_data/chooseModel.html',
                  {'title': title,
                   'module': moduleName,
                   'models': models,
                   'ordered_names': ordered_names,
                   'action': action,
                   'urlName': urlName,
                   }
                  )


def chooseSearchModel(request, searchModuleName):
    """
    List the models in the module, so they can be selected for search
    """
    return chooseModel(request, searchModuleName, 'Search ' + searchModuleName,
                       'search', 'xgds_data_searchChosenModel')


def csvEncode(something):
    """
    csvlib can't deal with non-ascii unicode, thus, this function
    """
    if isinstance(something, unicode):
        try:
            return something.encode("ascii", errors='xmlcharrefreplace')
        except TypeError:
            ## probably older python
            return something.encode("ascii", 'xmlcharrefreplace')
        # return something.encode("utf-8")
    else:
        return something


def formsetifyFieldName(i, fname):
    """
    Returns the field name for the ith form and given fname
    """
    return '-'.join(['form', str(i), fname])


def resolveSetting(configName, myModel, defaultSetting, override=None):
    """
    Figures out whether a specialized setting exists, or if the default should be used
    """
    setting = None
    if override:
        oconfig = override.get(configName,None)
    else:
        oconfig = None
    config = getattr(settings, configName, None)
    for model in myModel.__mro__:
        if issubclass(model, Model) and model != Model:
            if not setting and oconfig:
                setting = oconfig.get(model._meta.object_name, None)
            if not setting and config:
                setting = config.get(model._meta.object_name, None)
    if setting:
        return setting
    else:
        return defaultSetting


def searchSimilar(request, searchModuleName, searchModelName, pkid):
    """
    Launch point for finding more items like this one
    """
    reqlog = recordRequest(request)
    modelmodule = get_app(searchModuleName)
    myModel = getattr(modelmodule, searchModelName)
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

    multidict = QueryDict('fnctn=similar&form-TOTAL_FORMS=1', mutable=True)
    for fld in medict.keys():
        op = fld + '_operator'
        f = aForm.fields.get(op, None)
        if f is None:
            continue

        if f.choices.count(('IN~', 'IN~')):
            opval  = 'IN~'
        else:
            opval  = '='
        defaults[op] = opval
        multidict.appendlist(op, opval)

        # text or link fields- probably not what we want
        # if fld in aForm.fields:
        #     if medict[fld] is not None:
        #         fldVal = str(medict[fld])
        #         defaults[fld] = fldVal
        #         multidict.appendlist(fld, fldVal)

        for bfld in [fld + '_lo', fld + '_hi']:
            if bfld in aForm.fields:
                try:
                    ## probably not the smartest way to determine if
                    ## it's a time-based field
                    getTimePickerString(medict[fld])
                except AttributeError:
                    val = medict[fld]
                    defaults[bfld] = val
                    multidict.appendlist(bfld, val)

    simdata = MergeDict(multidict, defaults)

    return searchChosenModelCore(request, simdata, searchModuleName, searchModelName)


def searchHandoff(request, searchModuleName, searchModelName, fn, soft = True):
    """
    Simplified query parse and search, with results handed to given function
    """
    modelmodule = get_app(searchModuleName)
    myModel = getattr(modelmodule, searchModelName)
    tmpFormClass = SpecializedForm(SearchForm, myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    debug = []
    data = request.REQUEST

    results = None

    formset = tmpFormSet(data)
    if formset.is_valid():
        results, totalCount, hardCount = getMatches(myModel, formsetToQD(formset), soft)
    else:
        debug = formset.errors

    return fn(request, results)


def safegetattr(obj, attname, default = None):
    """ Because sometimes the database itself is inconsistent """
    try:
        return getattr(obj, attname, default)
    except:
        return None


def getPrimaryTimeField(model):
    fieldDict = dict([(f.name, f)
                      for f in model._meta.fields])
    try:
        for f in settings.XGDS_DATA_TIME_FIELDS:
            if f in fieldDict:
                return f
    except AttributeError:
        pass  # no worries
    return None


def getDtFromQueryParam(param):
    if param is None:
        return None
    else:
        return datetime.datetime.utcfromtimestamp(float(param))


def getTimePickerString(dt):
    """
    output time in format expected by jquery-ui timepicker addon
    """
    ## result = dt.strftime('%m/%d/%Y %I:%M:%S %p +0000')
    ## timeformat = resolveSetting('XGDS_DATA_TIME_FORMAT', myModel, 'hh:mm tt z')
    result = dt.strftime('%m/%d/%Y %H:%M +0000')
    result = re.sub('AM', 'am', result)
    result = re.sub('PM', 'pm', result)
    return result


def chooseCreateModel(request, createModuleName):
    """
    List the models in the module, so they can be selected for create
    """
    return chooseModel(request, createModuleName, 'Create ' + createModuleName,
                       'create', 'xgds_data_createChosenModel')


def createChosenModel(request, createModuleName, createModelName):
    """
    Create instance of the selected model
    """
    starttime = datetime.datetime.now()
    reqlog = recordRequest(request)
    modelmodule = get_app(createModuleName)
    myModel = getattr(modelmodule, createModelName)
    record = myModel.objects.create()
    try:
        ## try any specialized edit first
        return HttpResponseRedirect(record.get_edit_url())
    except AttributeError:
        return HttpResponseRedirect(reverse('xgds_data_editRecord', args=[createModuleName, createModelName, getattr(record,pk(record).name)]))


def editRecord(request, editModuleName, editModelName, rid):
    """
    Default edit for a record
    """
    reqlog = recordRequest(request)
    modelmodule = get_app(editModuleName)
    myModel = getattr(modelmodule, editModelName)
    tmpFormClass = SpecializedForm(EditForm, myModel)
    myFields = [x for x in modelFields(myModel) if not maskField(x) ]
    record = myModel.objects.get(pk=rid)
    if (request.REQUEST.get('fnctn',None) == 'edit'):
        form = tmpFormClass(request.POST)
        assert form.is_valid()
        changed = False
        for f in myFields:
            try:
                val = form.cleaned_data[f.name]
                oldval = getattr(record,f.name)
                try:
                    oldval = oldval.all()
                except AttributeError:
                    pass
                if val != oldval:
                    setattr(record,f.name,val)
                    changed = True
            except KeyError:
                pass

        if (changed):
            record.save()
        return HttpResponseRedirect(reverse('xgds_data_displayRecord', args=[editModuleName, editModelName, rid]))
    else:
        editee = myModel.objects.get(pk=rid)
        formData = dict()
        for f in myFields:
            val = getattr(editee,f.name)
            try: ## to get the id instead of the object
                val = pkValue(val)
            except AttributeError:
                pass # no id, no problem
            if isinstance(f, ManyToManyField):
                ## ModelMultipleChoiceField requires ids, not instances
                val = [ getattr(x,pk(x).name) for x in val.all()]
            formData[f.name] = val
        editForm = tmpFormClass(formData)
#        print(editForm)

        return log_and_render(request, reqlog, 'xgds_data/editRecord.html',
                          {'title': 'Editing ' + verbose_name(myModel) + ': ' + str(record),
                           'module': editModuleName,
                           'model': editModelName,
                           'displayFields': myFields,
                           'pk':  pk(myModel),
                           'record' : record,
                           'form' : editForm,
                           })


def displayRecord(request, displayModuleName, displayModelName, rid, force=False):
    """
    Default display for a record
    """
    reqlog = recordRequest(request)
    modelmodule = get_app(displayModuleName)
    myModel = getattr(modelmodule, displayModelName)
    record = myModel.objects.get(pk=rid)
    retformat = request.REQUEST.get('format', 'html')
    try:
        editable = settings.XGDS_DATA_EDITING
    except AttributeError:
        editable = False
    numeric = False
    for f in modelFields(myModel):
        if ordinalField(myModel, f) and not isinstance(f, DateTimeField):
            numeric = True

    try:
        ## try any specialized display first
        if not force:
            return HttpResponseRedirect(record.get_absolute_url())
    except AttributeError:
        pass # not defined

    myFields = [x for x in modelFields(myModel) if not maskField(x) ]
    if retformat == 'json':
        renderfn = log_and_json
    else:
        renderfn = log_and_render
    return renderfn(request, reqlog, 'xgds_data/displayRecord.html',
                              {'title': verbose_name(myModel) + ': ' + str(record),
                               'module': displayModuleName,
                               'model': displayModelName,
                               'verbose_model': verbose_name(myModel),
                               'editable': editable,
                               'allowSimiliar': numeric,
                               'displayFields': myFields,
                               'record' : record,
                               })


def resultsIdentity(request, results):
    """
    Annoying function to get around searchHandoff not having quite the right
    API for our use. Just returns the results.
    """
    return(results)


def selectForAction(request, moduleName, modelName, targetURLName,
                    finalAction, actionRenderFn, 
                    expert=False,passthroughs=dict()):
    """
    Search for and select objects for a subsequent action
    """
    override = {'XGDS_DATA_SEARCH_TEMPLATES': { modelName : 'xgds_data/selectForAction.html', },
                'XGDS_DATA_CHECKABLE': { modelName : True, },
                }

    if (request.REQUEST.get('userAction',None) == finalAction):
        ## should do something
        picks = request.REQUEST.getlist('picks')
        notpicks = request.REQUEST.getlist('notpicks')
        if request.REQUEST.get('allselected', False):
            for p in picks:
                try:
                    notpicks.remove(p)
                except ValueError:
                    pass
            objs = searchHandoff(request, moduleName, modelName, resultsIdentity)
            print('a',len(objs))
            if (len(notpicks) > 0):
                objs = objs.exclude(pk__in=[x.pk for x in retrieve(notpicks)])
            ## print(retrieve(notpicks))
        else:
            for p in notpicks:
                try:
                    picks.remove(p)
                except ValueError:
                    pass
            if (len(picks) > 0):
                myModel = resolveModel(moduleName, modelName)
                objs = myModel.objects.filter(pk__in=[x.pk for x in retrieve(picks)])
            else:
                objs = None
        return actionRenderFn(request, moduleName, modelName, objs)
    else:
        passes = { 'urlName' : targetURLName,
                   'finalAction' : finalAction }
        passes.update(passthroughs)
        return searchChosenModel(request, moduleName, modelName, expert, override=override, passthroughs=passes)


def chooseDeleteModel(request, deleteModuleName):
    """
    List the models in the module, so they can be selected for record deletion
    """
    return chooseModel(request, deleteModuleName, 'Search ' + deleteModuleName,
                       'delete', 'xgds_data_deleteMultiple')


def deleteMultiple(request, moduleName, modelName, expert=False):
    """
    Delete multiple objects
    """

    def actionRenderFn(request, moduleName, modelName, objs):
        if (objs):
            objs.delete()

        return HttpResponseRedirect(reverse('xgds_data_searchChosenModel', args=[moduleName, modelName]))

    return selectForAction(request, moduleName, modelName, 
                           'xgds_data_deleteMultiple',
                           'Delete Selected',
                           actionRenderFn,
                           expert=expert)


def deleteRecord(request, deleteModuleName, deleteModelName, rid):
    """
    Default delete for a record
    """
    reqlog = recordRequest(request)
    modelmodule = get_app(deleteModuleName)
    myModel = getattr(modelmodule, deleteModelName)
    record = myModel.objects.get(pk=rid)
    action = request.REQUEST.get('action',None)
    if (action == 'Cancel'):
        return HttpResponseRedirect(reverse('xgds_data_displayRecord', args=[deleteModuleName, deleteModelName, rid]))
    elif (action == 'Delete'):
        record.delete()
        return HttpResponseRedirect(reverse('xgds_data_searchChosenModel', args=[deleteModuleName, deleteModelName]))
    else:
        return log_and_render(request, reqlog, 'xgds_data/deleteRecord.html',
                              {'title': 'Delete ' + verbose_name(myModel) + ': ' + str(record),
                               'module': deleteModuleName,
                               'model': deleteModelName,
                               'verbose_model': verbose_name(myModel),
                               'record' : record,
                               })


def searchChosenModel(request, searchModuleName, searchModelName, expert=False, override=None, passthroughs=dict()):
    """
    Search over the fields of the selected model
    """
    data = request.REQUEST
    
    return searchChosenModelCore(request, data, searchModuleName, searchModelName, expert, override, passthroughs)


def keysMustBeAString(d):
    for k,v in d.items():
        if type(k) is not str:
            d[str(k)] = d[k]
            del d[k]
        try:
            keysMustBeAString(v)
        except AttributeError:
            pass

def log_and_json(request, reqlog, template, templateargs, nolog = None, listing = None):
    """
    experimenting with JSON
    """
    keysMustBeAString(templateargs)
    return HttpResponse(json.dumps(templateargs, default=jsonifier), content_type='application/json')


def searchChosenModelCore(request, data, searchModuleName, searchModelName, expert=False, override=None, passthroughs=dict()):
    """
    Search over the fields of the selected model
    """
    starttime = datetime.datetime.now()
    reqlog = recordRequest(request)
    modelmodule = get_app(searchModuleName)
    myModel = getattr(modelmodule, searchModelName)
    myFields = [x for x in modelFields(myModel) if not maskField(x) ]

    # If 'start' or 'end' query parameters are specified in the initial
    # GET method URL, use them to set initial values for the 'primary
    # time field', and auto-submit the search. This allows linking to search
    # results for a secified time interval from elsewhere in the system.
    initialData = {}
    autoSubmit = 0
    if request.method == 'GET':
        intvStart = getDtFromQueryParam(data.get('start'))
        intvEnd = getDtFromQueryParam(data.get('end'))
        primaryTimeField = getPrimaryTimeField(myModel)
        if intvStart:
            initialData[primaryTimeField + '_lo'] = getTimePickerString(intvStart)
        if intvEnd:
            initialData[primaryTimeField + '_hi'] = getTimePickerString(intvEnd)
        autoSubmit = 1 if bool(initialData) else 0

    tmpFormClass = SpecializedForm(SearchForm, myModel)
    tmpFormSet = formset_factory(tmpFormClass, extra=0)
    debug = []
    formCount = 1
    soft = True
    retformat = data.get('format', 'html')
    mode = data.get('fnctn', False)
    page = data.get('pageno', None)
    allselected = data.get('allselected', False)
    picks = data.getlist('picks')
    notpicks = data.getlist('notpicks')
    if (mode == 'selectall'):
        mode = 'query'
        allselected = True
        notpicks = []
    elif (mode == 'unselectall'):
        mode = 'query'
        allselected = False
        picks = []
    if (mode == 'csvhard'):
        soft = False
        mode = 'csv'
    if (mode == 'csv'):
        page = None
    else:
        pageSize = int(data.get('pageSize','25'))
        more = False
        if page:
            page = int(page)
        else:
            ## this is the first time through
            page = 1
    if allselected:
        for p in picks:
            try:
                notpicks.remove(p)
            except ValueError:
                pass
        picks = []
    else:
        for p in notpicks:
            try:
                picks.remove(p)
            except ValueError:
                pass
        notpicks = []
    results = None

    totalCount = None
    hardCount = None

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
                newdata.setlist(formsetifyFieldName(formCount, fname), val)
            elif ((not isinstance(field, forms.ChoiceField)) & (not field.initial   )):
                newdata[formsetifyFieldName(formCount, fname)] = unicode('')
            else:
                newdata[formsetifyFieldName(formCount, fname)] = unicode(field.initial)
        newdata['form-TOTAL_FORMS'] = unicode(formCount + 1)
        formset = tmpFormSet(newdata)  # but passing data nullifies extra
    elif ((mode == 'query') or (mode == 'csv') or (mode == 'similar')):
        if (mode == 'similar'):
            formCount = 1
            formset = tmpFormSet(initial=[data])
            ## unfortunately, initial form is not deemed valid
            ## so search won't happen first time
            ## can't spend more time on this now
        else:
            formCount = int(data['form-TOTAL_FORMS'])
            formset = tmpFormSet(data)
        if formset.is_valid():
            if page is not None:
                queryStart, queryEnd = pageLimits(page, pageSize)
            else:
                queryStart = 0
                queryEnd = None

            # if ishard(formset):
            #     hardCount = None
            # else:
            #     hardCount = getCount(myModel, formset, False)
            #     if hardCount > 100:
            #         soft = False

            results, totalCount, hardCount = getMatches(myModel, formsetToQD(formset), soft, \
                                                            queryStart, queryEnd)
            if hardCount is None:
                hardCount = totalCount

            more = queryStart + len(results) < totalCount
        else:
            for formdex in range(0,len(formset.errors)):
                for field, fielderrors in formset.errors[formdex].items():
                    for fedex in range(0,len(fielderrors)):
                        errmsg = fielderrors[fedex]
                        if errmsg == 'Select a valid choice. That choice is not one of the available choices.':
                            fielderrors[fedex] = 'Select a valid choice. Valid choices are {0}'.format(', '.join([x[1] for x in formset[formdex].fields[field].choices]))
            debug = formset.errors
    elif (mode == 'change'):
        formCount = int(data['form-TOTAL_FORMS'])
        formset = tmpFormSet(data)
##    elif (mode == 'similar'):
##        formset = tmpFormSet(initial=[data])
    else:
        formset = tmpFormSet(initial=[initialData])

    if (mode == 'csv'):

        content_type = 'text/csv'
        extension = '.csv'

        try:
            ecsv = __import__('.'.join([searchModuleName, 'exportCsv']))
            ##print(ecsv.exportCsv.exportCsv)
            meta, content = ecsv.exportCsv.exportCsv(results)

            content_type = meta.get('content_type', content_type)
            extension = meta.get('extension', extension)

            response = HttpResponse(content, content_type=content_type)
            response['Content-Disposition'] = 'attachment; filename='+ verbose_name(myModel) + extension
        except ImportError:
            response = HttpResponse(content_type='text/csv')
            # if you want to download instead of display in browser
            response['Content-Disposition'] = 'attachment; filename='+ verbose_name(myModel) + '.csv'
            writer = csv.writer(response)
            writer.writerow([f.verbose_name for f in myFields])
            for r in results:
            ##            r.get(f.name,None)
                ## writer.writerow([csvEncode(safegetattr(r, f.name, None)) for f in myFields ])
                row = []
                for f in myFields:
                    val = xgds_data_extras.getattribute(r, f)
                    if isinstance(f, models.ImageField):
                        val = f.storage.url(val)
                    elif isinstance(f, models.ManyToManyField):
                        results = []
                        for v in val:
                            results.append(unicode(v))
                        val = '"{0}"'.format(','.join(results))   
                    elif isinstance(val, basestring):
                        pass
                    elif isinstance(val, User):
                        val = ', '.join([val.last_name, val.first_name])
                    else:
                        try:
                            val = val()
                        except TypeError:
                            pass
                        try:
                            val = ', '.join(unicode(x) for x in val)
                        except TypeError:
                            pass
                    row.append(val)
                writer.writerow([csvEncode(x) for x in row ])
                

        if logEnabled():
            reslog = ResponseLog.create(request=reqlog)
            reslog.save()
            recordList(reslog, results)
        return response
    else:
        datetimefields = []
        for x in myFields:
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
        template = resolveSetting('XGDS_DATA_SEARCH_TEMPLATES', myModel, 'xgds_data/searchChosenModel.html', override=override)
        checkable = resolveSetting('XGDS_DATA_CHECKABLE', myModel, False, override=override)
        timeformat = resolveSetting('XGDS_DATA_TIME_FORMAT', myModel, 'hh:mm tt z', override=override)
        if results is None:
            resultfullids = dict()
        else:
            resultfullids = dict([ (r, fullid(r)) for r in results ])
            pfs = [ f.name for f in modelFields(myModel) if isinstance(f,related.RelatedField) and not maskField(f) ]
            try:
                results = results.prefetch_related(*pfs)
            except AttributeError:
                pass # probably got list-ified

        vname =  verbose_name(myModel)

        templateargs = {'title': 'Search ' + vname,
                        'resultfullids' : resultfullids,
                        'module': searchModuleName,
                        'model': searchModelName,
                        'standalone': not GEOCAMUTIL_FOUND,
                        'expert': expert,
                        # 'pk':  pk(myModel),
                        'datetimefields': datetimefields,
                        'timeformat': timeformat,
                        'displayFields': myFields,
                        'formset': formset,
                        'axesform': axesform,
                        'results': results,
                        'count': totalCount,
                        'exactCount': hardCount,
                        'duration': total_seconds(datetime.datetime.now() - starttime),
                        'page': page,
                        'pageSize': pageSize,
                        'more': more,
                        'checkable': checkable,
                        'picks': picks,
                        'notpicks': notpicks,
                        'allselected': allselected,
                        'debug': debug,
                        'autoSubmit': autoSubmit,
                        }
        templateargs.update(passthroughs)
        if retformat == 'json':
            renderfn = log_and_json
        else:
            renderfn = log_and_render
        return renderfn(request, reqlog, template,
                        templateargs,
                        nolog=['formset', 'axesform', 'results', 'resultsids', 'scores'],
                        listing=results)


def megahandler(obj):
    try:
        return ', '.join([ str(x) for x in obj.all() ])
    except AttributeError:
        if isinstance(obj, datetime.datetime):
            return calendar.timegm(obj.timetuple()) * 1000
        elif isinstance(obj, Model):
            return escape(str(obj))
        elif isinstance(obj, (int, long, float, complex)):
            return obj
        else:
            return escape(obj)


def getRelated(modelField):
    return dict([ (getattr(x, pk(x).name), escape(str(x)))
            for x in modelField.rel.to.objects.all() ])


def jsonifier(obj,level=2):
    try:
        return calendar.timegm(obj.timetuple()) * 1000
    except AttributeError:
        pass

    try:
        ret =[ jsonifier(f,level=level-1) for f in obj.forms ]
        #for k in dir(obj):
        #    print(k,getattr(obj,k))
        #print(obj)
        return ret
    except AttributeError:
        pass

    try:
        #ret = jsonifier(obj.fields)
        #for k in ['add_error', 'add_initial_prefix', 'add_prefix', 'as_expert_table', 'as_p', 'as_table', 'as_ul', 'auto_id', 'base_fields', 'changed_data', 'clean', 'data', u'declared_fields', 'empty_permitted', 'error_class', 'errors', 'fields', 'files', 'full_clean', 'has_changed', 'hidden_fields', 'initial', 'is_bound', 'is_multipart', 'is_valid', 'label_suffix', 'media', 'model', 'modelVerboseName', 'non_field_errors', 'prefix', 'visible_fields']:
         #   print(k,getattr(obj,k))
        return (obj.prefix,dict([('errors', jsonifier(obj.errors,level=level-1)), 
                                 ('fields', jsonifier(obj.fields,level=level-1))]))
    except AttributeError:
        pass

    try:
        return dict([(str(k), jsonifier(v,level=level-1)) for k,v in obj.items()])
    except AttributeError:
        pass

    try: # field stuff
        stuff = dict()
        for k in [# "bound_data",   # instancemethod
                  # "choices",     # ModelChoiceIterator
                  # "empty_values",   # maybe not interesting
                  # "error_messages",   # dict
                  "help_text",   
                  "initial",   
                  "label",   
                  "required",   
                  "show_hidden_initial",   
                  # "valid_value",   # instancemethod
        ]:
            stuff[k] = getattr(obj,k)
            # stuff['choices'] = jsonifier(list(getattr(obj,'choices')),level=level-1)
        return stuff
    except AttributeError:
        pass

    if isinstance(obj,(ErrorDict,ErrorList)):
        return obj

    if (level > 0):
        try:
            return dict([(f.name,jsonifier(safegetattr(obj,f.name),level=level-1)) for f in modelFields(obj) if not maskField(f)])
        except AttributeError:
            pass

    try:
        return obj.name
    except AttributeError:
        pass

    try:
        return list(obj.values())
    except AttributeError:
        pass

    if isinstance(obj, (Model,unicode, str)):
        return str(obj)
    elif obj is None or isinstance(obj, (bool, int, long, float)):
        return obj
    else:
        return '{0}: {1}'.format(str(obj.__class__),str(obj))
        # return dir(obj)


def plotQueryResults(request, searchModuleName, searchModelName, start, end, soft=True):
    """
    Plot the results of a query
    """
    start = int(start)
    end = int(end)
    reqlog = recordRequest(request)
    modelmodule = __import__('.'.join([searchModuleName, 'models'])).models
    myModel = getattr(modelmodule, searchModelName)
    myFields = [ x for x in modelFields(myModel) if not maskField(x) ]
    tmpFormClass = SpecializedForm(SearchForm, myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    data = request.REQUEST
    soft = soft in (True, 'True')

    axesform = AxesForm(myFields, data)
    fieldDict = dict([ (x.name, x) for x in myFields ])
    timeFields = [fieldName
                  for fieldName, fieldVal in fieldDict.iteritems()
                  if isinstance(fieldVal, (DateField, TimeField))]

    formset = tmpFormSet(data)
    if formset.is_valid():
        ## a lot of this code mimics what is in searchChosenModel
        ## should figure out a way of centralizing instead of copying

        plotdata = []
        pkName = pk(myModel).name
        objs, totalCount, hardCount = getMatches(myModel, formsetToQD(formset), soft, start, end)
       
        pfs = [ f.name for f in modelFields(myModel) if isinstance(f,related.RelatedField) and not maskField(f) ]
        try:
            objs = objs.prefetch_related(*pfs)
        except AttributeError:
            pass # probably got list-ified

        
        for x in objs:
            pdict = { pkName: x.pk }
            for fld in myFields:
                val =  megahandler(safegetattr(x, fld.name, None))
                try:
                    pdict[fld.name] = val.name
                except AttributeError:
                    pdict[fld.name] = val
            plotdata.append(pdict)
        pldata = [str(x) for x in objs]

        ## the following code determines if there are any foreign keys that can be selected, and if so,
        ## replaces the corresponding values (which will be ids) with the string representation
        seriesChoices = dict(axesform.fields['series'].choices)

        seriesValues = dict([ (m.name, getRelated(m))
                        for m in myFields
                        if ((m.name in seriesChoices) and (m.rel is not None) )])
        for x in plotdata:
            for k in seriesValues.keys():
                if x[k] is not None:
                    try:
                        x[k] = seriesValues[k][x[k]]
                    except:  # pylint: disable=W0702
                        x[k] = str(x[k])  # seriesValues[k][seriesValues[k].keys()[0]]

        debug = []
        #totalCount = myModel.objects.filter(filters).count()
        shownCount = len(pldata)
    else:
        debug = [(x, formset.errors[x]) for x in formset.errors]
        totalCount = None
        pldata = []
        plotdata = []
        objs = []

    template = resolveSetting('XGDS_DATA_PLOT_TEMPLATES', myModel, 'xgds_data/plotQueryResults.html')
    return log_and_render(request, reqlog, template,
                          {'title': 'Plot ' + verbose_name(myModel),
                           'standalone': not GEOCAMUTIL_FOUND,
                           'plotData': json.dumps(plotdata, default=jsonifier),
                           'labels': pldata,
                           'timeFields': json.dumps(timeFields),
                           'module': searchModuleName,
                           'model': searchModelName,
                           'pk': pk(myModel).name,
                           'start': start,
                           'end': end,
                           'soft': soft,
                           'debug': debug,
                           'count': totalCount,
                           'showncount': shownCount,
                           "formset": formset,
                           'axesform': axesform
                           },
                          nolog=['plotData', 'labels', 'formset', 'axesform'],
                          listing=objs)


def editCollection(request, rid):
    """
    edit a collection of data
    """
    editModuleName = moduleName(Collection)
    editModelName = modelName(Collection)
    ## UGH - this is copy of edit collection just to change the template,
    ## just to change the submit url
    ## Need to fix
    reqlog = recordRequest(request)
    modelmodule = get_app(editModuleName)
    myModel = getattr(modelmodule, editModelName)
    tmpFormClass = SpecializedForm(EditForm, myModel)
    myFields = [x for x in modelFields(myModel) if not maskField(x) ]
    record = myModel.objects.get(pk=rid)
    retformat = request.REQUEST.get('format', 'html')
    if (request.REQUEST.get('fnctn',None) == 'edit'):
        form = tmpFormClass(request.POST)
        assert form.is_valid()
        changed = False
        for f in myFields:
            try:
                val = form.cleaned_data[f.name]
                oldval = getattr(record,f.name)
                try:
                    oldval = oldval.all()
                except AttributeError:
                    pass
                if val != oldval:
                    setattr(record,f.name,val)
                    changed = True
            except KeyError:
                pass

        if (changed):
            record.save()
        return HttpResponseRedirect(reverse('xgds_data_displayRecord', args=[editModuleName, editModelName, rid]))
    else:
        editee = myModel.objects.get(pk=rid)
        formData = dict()
        for f in myFields:
            val = getattr(editee,f.name)
            try: ## to get the id instead of the object
                val = pkValue(val)
            except AttributeError:
                pass # no id, no problem
            if isinstance(f, ManyToManyField):
                ## ModelMultipleChoiceField requires ids, not instances
                val = [ getattr(x,pk(x).name) for x in val.all()]
            formData[f.name] = val
        editForm = tmpFormClass(formData)

        if retformat == 'json':
            renderfn = log_and_json
        else:
            renderfn = log_and_render
        return renderfn(request, reqlog, 'xgds_data/editCollection.html',
                          {'title': 'Editing ' + verbose_name(myModel) + ': ' + str(record),
                           'module': editModuleName,
                           'model': editModelName,
                           'displayFields': myFields,
                           'pk':  pk(myModel),
                           'record' : record,
                           'form' : editForm,
                           })



def createCollection(request, groupModuleName, groupModelName, expert=False):
    """
    create a collection of data
    """

    def actionRenderFn(request, groupeeModuleName, groupeeModelName, objs):
        coll = Collection.objects.create()
        links = []
        for inst in objs:
            links.append(GenericLink.objects.create(link=inst))

        if len(links) > 0:
            ## Boo- bulk_create doesn't get the ids, so we can't subsequently link
            ##GenericLink.objects.bulk_create(links)
            coll.contents.add(*links)
        coll.save()

        try:
            ## try any specialized edit first
            return HttpResponseRedirect(coll.get_edit_url())
        except AttributeError:
            return HttpResponseRedirect(reverse('xgds_data_editRecord', args=[moduleName(Collection), modelName(Collection), pkValue(coll)]))

    return selectForAction(request, groupModuleName, groupModelName, 
                           'xgds_data_createCollection',
                           'Group Selected',
                           actionRenderFn,
                           expert=expert)


def getCollectionContents(request, rid):
    """
    Stuff in a collection
    """
    reqlog = recordRequest(request)
    record = Collection.objects.get(pk=rid)
    stuff = record.resolvedContents()
    retformat = request.REQUEST.get('format', 'html')
    for x in modelFields(GenericLink):
        if x.name == 'link':
            field = x
    if retformat == 'json':
        renderfn = log_and_json
    else:
        renderfn = log_and_render
    return renderfn(request, reqlog, 'xgds_data/collectionContents.html',
                              {'title': 'Contents of ' + str(record),
                               'field': field,
                               'contents' : stuff,
                               })

#if logEnabled():
def replayRequest(request, rid):
    reqlog = RequestLog.objects.get(id=rid)
    reqargs = RequestArgument.objects.filter(request=reqlog)
    view, args, kwargs = resolve(reqlog.path)
    onedict = {}
    multidict = QueryDict('', mutable=True)
    for arg in reqargs:
        onedict[arg.name] = arg.value
        multidict.appendlist(arg.name, arg.value)
    if ('format' in request.REQUEST):
        argname = unicode('format')
        argvalue = request.REQUEST.get('format')
        onedict[argname] = argvalue
        multidict.appendlist(argname, argvalue)
    redata = MergeDict(multidict, onedict)
    rerequest = HttpRequestReplay(request, reqlog.path, redata)
    kwargs['request'] = rerequest

    print(request.REQUEST)
    print(redata)

    return view(*args, **kwargs)
