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

#import sys
import re
import traceback
import json
import csv
import datetime
import calendar
#import StringIO
from itertools import chain

#import pytz

from django.apps import apps
from django import forms
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import (resolve, reverse, NoReverseMatch)
#from django.template import RequestContext
#from django.db import connection, DatabaseError
from django.db import models
from django.db.models import (ManyToManyField, Model)
from django.db.models.fields import DateTimeField, DateField, TimeField, related
from django.forms.models import ModelMultipleChoiceField, model_to_dict

from django.forms.formsets import formset_factory
from django.utils.html import escape
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (ValidationError, ObjectDoesNotExist)

try:
    from geocamUtil.loader import getModelByName
    GEOCAMUTIL_FOUND = True
except ImportError:
    GEOCAMUTIL_FOUND = False

from django.conf import settings
from xgds_data.introspection import (modelFields, maskField, resolveField, isAbstract,
                                     resolveModel, ordinalField,
                                     pk, pkValue, verbose_name, verbose_name_plural,
                                     settingsForModel,
                                     modelName, moduleName, fullid)
from xgds_data.forms import QueryForm, SearchForm, EditForm, AxesForm, SpecializedForm, ImportInstrumentDataForm
from xgds_data.models import Collection, GenericLink
from xgds_data.dlogging import recordRequest, recordList, log_and_render
from xgds_data.logconfig import logEnabled
from xgds_data.search import getMatches, pageLimits, retrieve
from xgds_data.utils import total_seconds, getDataFromRequest
from xgds_data.templatetags import xgds_data_extras

from django.http import QueryDict
try:
    from django.forms.utils import ErrorList, ErrorDict
except ImportError:
    pass

if logEnabled():
    from xgds_data.models import RequestLog, RequestArgument, ResponseLog, HttpRequestReplay

queryCache = {}

def formsetToQD(formset):
    return [form.cleaned_data for form in formset]


def index(request):
    return HttpResponse("Hello, world. You're at the xgds_data index.")


def hasModels(appName):
    return len([m for m in apps.get_app_config(appName).get_models()]) != 0


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
    nestedModels = [[m for m in appConfig.get_models()]
                    for appConfig in apps.get_app_configs()
                    if not isSkippedApp(appConfig.name)]
    return dict([(model.__name__, model) for model in list(chain(*nestedModels)) if not isAbstract(model)])

if (hasattr(settings, 'XGDS_DATA_SEARCH_MODELS')):
    SEARCH_MODELS = dict([(name, getModelByName(name))
                          for name in settings.XGDS_DATA_SEARCH_MODELS])
else:
    SEARCH_MODELS = searchModelsDefault()

MODELS_INFO = [getModelInfo(_qname, _model)
               for _qname, _model in SEARCH_MODELS.iteritems()]


# def searchIndex(request):
#     return render_to_response('xgds_data/searchIndex.html',
#                               {'models': MODELS_INFO},
#                               context_instance=RequestContext(request))


# def searchModel(request, searchModelName):
#     if request.method not in ('GET', 'POST'):
#         return HttpResponseNotAllowed(['GET', 'POST'])

#     model = SEARCH_MODELS[searchModelName]
#     tableName = model._meta.db_table
#     modelInfo = getModelInfo(searchModelName, model)

#     fieldLookup = dict(((field.name, field)
#                         for field in model._meta._fields()))
#     timestampField = None
#     for field in ('timestampSeconds', 'timestamp'):
#         if field in fieldLookup:
#             timestampField = field
#             break

#     if request.method == 'POST':
#         form = QueryForm(request.POST)
#         assert form.is_valid()
#         userQuery = form.cleaned_data['query']
#         escapedUserQuery = re.sub(r'%', '%%', userQuery)
#         mostRecentFirst = form.cleaned_data['mostRecentFirst']

#         prefix = 'SELECT * FROM %s ' % tableName
#         countPrefix = 'SELECT COUNT(*) FROM %s ' % tableName
#         order = ''
#         if mostRecentFirst and timestampField:
#             order += ' ORDER BY %s DESC ' % timestampField
#         limit = ' LIMIT 100'

#         countQuery = countPrefix + escapedUserQuery
#         sqlQuery = prefix + escapedUserQuery + order + limit
#         # escape % signs, interpreted by Django raw() as template format

#         styledSql = (prefix
#                      + '<span style="color: blue;">%s</span>' % userQuery
#                      + order
#                      + limit)

#         try:
#             cursor = connection.cursor()
#             cursor.execute(countQuery)
#             count = cursor.fetchone()[0]

#             matches = list(model.objects.raw(sqlQuery))

#             wasError = False
#         except DatabaseError:
#             sys.stderr.write(traceback.format_exc())
#             wasError = True
#             result = {
#                 'sql': styledSql,
#                 'summary': 'database error!',
#                 'matches': [],
#             }
#         if not wasError:
#             result = {
#                 'sql': styledSql,
#                 'summary': '%s matches (showing at most 100)' % count,
#                 'matches': matches,
#             }
#     else:
#         # GET method
#         form = QueryForm()
#         result = None
#     return render_to_response('xgds_data/searchModel.html',
#                               {'model': modelInfo,
#                                'models': MODELS_INFO,
#                                'form': form,
#                                'result': result},
#                               context_instance=RequestContext(request))


def chooseSearchApp(request):
    appList = [appConfig.name for appConfig in apps.get_app_configs()]
    appList = [re.sub(r'\.models$', '', app) for app in appList]
    appList = [app for app in appList
            if (not isSkippedApp(app)) and hasModels(app)]
    return render(request,
                  'xgds_data/chooseSearchApp.html',
                  {'title': 'Search Apps',
                   'apps': appList})


def chooseModel(request, moduleName, title, action, urlName):
    """
    List the models in the module, so they can be selected
    """
    appConfig = apps.get_app_config(moduleName)
    models = dict([(verbose_name(m), m) for m in appConfig.get_models() if not isAbstract(m)])
    ordered_names = sorted(models.keys())

    return render(request, 'xgds_data/chooseModel.html',
                  {'title': title,
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


def searchSimilar(request, searchModuleName, searchModelName, pkid,
                                   queryGenerator=None):
    """
    Launch point for finding more items like this one
    """
    ##reqlog = recordRequest(request)
    myModel = apps.get_model(searchModuleName, searchModelName)
    myFields = modelFields(myModel)
    tmpFormClass = SpecializedForm(SearchForm, myModel,
                                   queryGenerator=queryGenerator)
    tmpFormSet = formset_factory(tmpFormClass, extra=0)
    debug = []
    data = getDataFromRequest(request)
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

    defaults.update(multidict)

    return searchChosenModelCore(request, defaults, searchModuleName, searchModelName)


def searchHandoff(request, searchModuleName, searchModelName, fn,
                  soft = True, queryGenerator=None):
    """
    Simplified query parse and search, with results handed to given function
    """
    myModel = apps.get_model(searchModuleName, searchModelName)
    tmpFormClass = SpecializedForm(SearchForm, myModel,
                                   queryGenerator=queryGenerator)
    tmpFormSet = formset_factory(tmpFormClass)
    debug = []
    data = getDataFromRequest(request)

    results = None

    formset = tmpFormSet(data)
    if formset.is_valid():
        results, hardCount, totalCount = queryLogic(myModel, formset, soft = soft, queryGenerator=queryGenerator)
        # if (soft):
        #     results = getMatches(myModel, formsetToQD(formset))
        # else:
        #     results = getMatches(myModel, formsetToQD(formset), threshold = 1.0)
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
    myModel = apps.get_model(createModuleName, createModelName)
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
    myModel = apps.get_model(editModuleName, editModelName)
    tmpFormClass = SpecializedForm(EditForm, myModel)
    myFields = [x for x in modelFields(myModel) if not maskField(x) ]
    record = myModel.objects.get(pk=rid)
    if (getDataFromRequest(request).get('fnctn',None) == 'edit'):
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
    myModel = apps.get_model(displayModuleName, displayModelName)
    try:
        record = myModel.objects.get(pk=rid)
        retformat = getDataFromRequest(request).get('format', 'html')
        try:
            if settings.XGDS_DATA_EDITING:
                try: ## try any specialized edit first
                    editURL = record.get_edit_url()
                except AttributeError:
                    editURL = reverse('xgds_data_editRecord',
                                      args=[displayModuleName, displayModelName, pkValue(record)])
            else:
                editURL = None
        except AttributeError:
            editURL = None
        numeric = False
        for f in modelFields(myModel):
            if (ordinalField(myModel, f) and not isinstance(f, DateTimeField)
                and not maskField(f)):
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

        template = resolveSetting('XGDS_DATA_DISPLAY_TEMPLATES', myModel, 'xgds_data/displayRecord.html')
        return renderfn(request, reqlog, template,
                                  {'title': verbose_name(myModel) + ': ' + str(record),
                                   'module': displayModuleName,
                                   'model': displayModelName,
                                   'verbose_model': verbose_name(myModel),
                                   'editURL': editURL,
                                   'allowSimiliar': numeric,
                                   'displayFields': myFields,
                                   'record' : record,
                                   })
    except (ObjectDoesNotExist, ValueError):
        return HttpResponse("Invalid id provided.")


def resultsIdentity(request, results):
    """
    Annoying function to get around searchHandoff not having quite the right
    API for our use. Just returns the results.
    """
    return(results)


def selectForAction(request, moduleName, modelName, targetURLName,
                    finalAction, actionRenderFn,
                    expert=False, passthroughs=dict(), queryGenerator=None,
                    confirmed=False):
    """
    Search for and select objects for a subsequent action
    """
    engaged = (getDataFromRequest(request).get('fnctn',None) == finalAction)
    if engaged and confirmed:
        ## should do something
        picks = getDataFromRequest(request).getlist('picks')
        notpicks = getDataFromRequest(request).getlist('notpicks')
        if getDataFromRequest(request).get('allselected', False):
            for p in picks:
                try:
                    notpicks.remove(p)
                except ValueError:
                    pass
            objs = searchHandoff(request, moduleName, modelName, resultsIdentity)
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
                ## this annoying reretrieving is only to make
                ## objs a queryset instead of a list
                objs = myModel.objects.filter(pk__in=[x.pk for x in retrieve(picks)])
            else:
                objs = None

        return actionRenderFn(request, moduleName, modelName, objs)
    elif engaged:
        passes = { 'urlName' : targetURLName,
                   'finalAction' : finalAction,
                   }
        passes.update(passthroughs)
        override = {'XGDS_DATA_SEARCH_TEMPLATES': { modelName : 'xgds_data/confirmAction.html', },
                    'XGDS_DATA_CHECKABLE': { modelName : True, },
                    }

        picks = getDataFromRequest(request).getlist('picks')

        return searchChosenModel(request, moduleName, modelName, expert, override=override, passthroughs=passes, queryGenerator=queryGenerator)
    else:
        passes = { 'urlName' : targetURLName,
                   'finalAction' : finalAction }
        passes.update(passthroughs)
        override = {'XGDS_DATA_SEARCH_TEMPLATES': { modelName : 'xgds_data/selectForAction.html', },
                    'XGDS_DATA_CHECKABLE': { modelName : True, },
                    }

        return searchChosenModel(request, moduleName, modelName, expert, override=override, passthroughs=passes, queryGenerator=queryGenerator)


def chooseDeleteModel(request, deleteModuleName):
    """
    List the models in the module, so they can be selected for record deletion
    """
    return chooseModel(request, deleteModuleName, 'Search ' + deleteModuleName,
                       'delete', 'xgds_data_deleteMultiple')


def defaultPage(fallbackURLName, fallbackArgs):
    """
    Go to a default page after completing some action.
    """
    try:
        return HttpResponseRedirect(reverse(settings.XGDS_DATA_SITE_HOME))
    except NoReverseMatch:
        print("XGDS_DATA_SITE_HOME is misconfigured, pointing to {0} which is not a reversable URL reference".format(settings.XGDS_DATA_SITE_HOME))
    except AttributeError:
        pass # not specified, but that's ok

    return HttpResponseRedirect(reverse(fallbackURLName, args=fallbackArgs))


def deleteMultiple(request, moduleName, modelName, expert=False, override=None, passthroughs=dict(), queryGenerator=None):
    """
    Delete multiple objects
    """

    def actionRenderFn(request, moduleName, modelName, objs):
        # return deleteRecord(request, moduleName, modelName, objs=objs)
        # return HttpResponseRedirect(reverse('xgds_data_deleteRecord',
        #                                     args=[moduleName, modelName, pkValue(objs[0])]))

        if (objs):
            objs.delete()

        args = [moduleName, modelName]
        if expert:
            args.append('expert')

        return defaultPage('xgds_data_deleteMultiple', args)

        # return HttpResponseRedirect(reverse('xgds_data_deleteMultiple',
        #                                     args=[moduleName, modelName],
        #                                     kwargs={'expert':expert,
        #                                             'override':override,
        #                                             'passthroughs':passthroughs,
        #                                             'searchFn':searchFn}))

    confirmed = getDataFromRequest(request).get('confirmed',False)
    return selectForAction(request, moduleName, modelName,
                           'xgds_data_deleteMultiple',
                           'Delete Selected',
                           actionRenderFn,
                           expert=expert,
#                           override=override,
                           passthroughs=passthroughs,
                           queryGenerator=queryGenerator,
                           confirmed=confirmed)


def deleteRecord(request, deleteModuleName, deleteModelName, rid=None, objs=None):
    """
    Default delete for a record
    """
    reqlog = recordRequest(request)
    myModel = apps.get_model(deleteModuleName, deleteModelName)
    ## objects are either give by pk (rid), passed in (objs), or submitted in
    ## form (picks). Ugh!
    if objs is not None:
        pass
    elif rid is not None:
        objs = myModel.objects.filter(pk=rid)
    else:
        picks = getDataFromRequest(request).getlist('picks')
        if (len(picks) > 0):
            objs = retrieve(picks, flat=False)
            if (len(objs) > 1):
                newobjs = []
                for qset in objs:
                    newobjs.extend(qset)
                objs = newobjs
            elif (len(objs) == 1):
                objs = objs[0]

    if objs is None:
        objs = []

    recordfullids = [ fullid(r) for r in objs ]
    action = getDataFromRequest(request).get('action',None)
    if (action == 'Cancel'):
        return defaultPage('xgds_data_displayRecord', [deleteModuleName, deleteModelName, rid])
    elif (action == 'Delete'):
        ## need a queryset to delete
        ## objs = myModel.objects.filter(pk__in=[x.pk for x in objs])
        try:
            objs.delete()
        except AttributeError:
            ## TODO: Handle this situation
            pass # it's a list
        return defaultPage('xgds_data_searchChosenModel',
                           [deleteModuleName, deleteModelName])
    else:
        if len(objs) == 1:
            title = 'Delete ' + verbose_name(myModel) + ': ' + str(objs[0])
        else:
            title = 'Delete ' + str(len(objs)) + ' ' + verbose_name_plural(myModel)

        return log_and_render(request, reqlog, 'xgds_data/deleteRecord.html',
                              {'title': title,
                               'module': deleteModuleName,
                               'model': deleteModelName,
                               'verbose_model': verbose_name(myModel),
                               'verbose_model_plural': verbose_name_plural(myModel),
                               'records' : objs,
                               'recordfullids' : recordfullids,
                               })


def searchChosenModel(request, searchModuleName, searchModelName, expert=False, override=None, passthroughs=dict(), queryGenerator=None):
    """
    Search over the fields of the selected model
    """
    data = getDataFromRequest(request)

    return searchChosenModelCore(request, data, searchModuleName, searchModelName,
                                 expert=expert, override=override, passthroughs=passthroughs, queryGenerator=queryGenerator)


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
    return HttpResponse(json.dumps(templateargs, default=jsonify), content_type='application/json')


def queryLogic(myModel, formset, queryStart = None, queryEnd = None,
               soft = True, queryGenerator=None):
    """
    query logic
    """
    hardresults = getMatches(myModel,formsetToQD(formset),
                             threshold=1.0,
                             queryGenerator=queryGenerator)
    try:
        hardCount = hardresults.count()
    except (AttributeError, TypeError):
        hardCount = len(hardresults)
    if (hardCount <= 1E2) and soft:
        results = getMatches(myModel,formsetToQD(formset),
                             queryGenerator=queryGenerator)
        try:
            totalCount = results.count()
        except (AttributeError, TypeError):
            totalCount = len(results)
    else:
        results = hardresults
        totalCount = hardCount

    if (queryEnd is not None) and (queryStart is None):
        results = results[0:queryEnd]
    elif (queryEnd is None) and (queryStart is not None):
        results = results[queryStart:totalCount]
    elif (queryEnd is not None) and (queryStart is not None):
        results = results[queryStart:queryEnd]

    return (results, hardCount, totalCount)
    # results, totalCount, hardCount = getMatches(myModel,
    #                                             formsetToQD(formset),
    #                                             soft,
    #                                             queryStart = queryStart,
    #                                             queryEnd = queryEnd,
    #                                             queryGenerator=queryGenerator)


def searchChosenModelCore(request, data, searchModuleName, searchModelName, expert=False, override=None, passthroughs=dict(), queryGenerator=None):
    """
    Search over the fields of the selected model
    """
    starttime = datetime.datetime.now()
    reqlog = recordRequest(request)
    myModel = apps.get_model(searchModuleName, searchModelName)
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


    tmpFormClass = SpecializedForm(SearchForm, myModel,
                                   queryGenerator=queryGenerator)
    tmpFormSet = formset_factory(tmpFormClass, extra=0)
    debug = []
    formCount = 1
    soft = True
    retformat = data.get('format', 'html')
    mode = data.get('fnctn', None)
    page = data.get('pageno', None)
    allselected = data.get('allselected', False)
    picks = data.getlist('picks')
    notpicks = data.getlist('notpicks')
    if (mode == 'selectall'):
        ##mode = 'query'
        allselected = True
        notpicks = []
    elif (mode == 'unselectall'):
        ##mode = 'query'
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
    elif (mode == 'change'):
        formCount = int(data['form-TOTAL_FORMS'])
        formset = tmpFormSet(data)
##    elif (mode == 'similar'):
##        formset = tmpFormSet(initial=[data])
    elif (mode == None):
        formset = tmpFormSet(initial=[initialData])
    ##elif ((mode == 'query') or (mode == 'csv') or (mode == 'similar')):
    else:
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
                queryStart = None # was 0
                queryEnd = None

            # if ishard(formset):
            #     hardCount = None
            # else:
            #     hardCount = getCount(myModel, formset, False)
            #     if hardCount > 100:
            #         soft = False
            results, hardCount, totalCount = queryLogic(myModel, formset,
                                                        queryStart = queryStart,
                                                        queryEnd = queryEnd,
                                                        soft = soft, queryGenerator=queryGenerator)
            # hardresults = getMatches(myModel,formsetToQD(formset),
            #                          threshold=1.0,
            #                          queryGenerator=queryGenerator)
            # hardCount = hardresults.count()
            # try:
            #     hardCount = hardresults.count()
            # except (AttributeError, TypeError):
            #     hardCount = len(hardresults)

            # if (hardCount <= 1E2) and soft:
            #     results = getMatches(myModel,formsetToQD(formset),
            #                          queryGenerator=queryGenerator)
            #     try:
            #         totalCount = results.count()
            #     except (AttributeError, TypeError):
            #         totalCount = len(results)
            # else:
            #     results = hardresults
            #     totalCount = hardCount

            # if (queryEnd is not None) and (queryStart is None):
            #     results = results[0:queryEnd]
            # elif (queryEnd is None) and (queryStart is not None):
            #     results = results[queryStart:totalCount]
            # elif (queryEnd is not None) and (queryStart is not None):
            #     results = results[queryStart:queryEnd]

            # results, totalCount, hardCount = getMatches(myModel,
            #                                             formsetToQD(formset),
            #                                             soft,
            #                                             queryStart = queryStart,
            #                                             queryEnd = queryEnd,
            #                                             queryGenerator=queryGenerator)
            pfs = [ f.name for f in modelFields(myModel) if isinstance(f,related.RelatedField) and not maskField(f) ]
            try:
                results = results.prefetch_related(*pfs)
            except AttributeError:
                pass # probably got list-ified
            if totalCount:
                results = list(results)
            else:
                ## saves time if this was an expensive query
                ## we already know there are no results
                results = list()

            if queryStart:
                more = queryStart + len(results) < totalCount
        else:
            for formdex in range(0,len(formset.errors)):
                for field, fielderrors in formset.errors[formdex].items():
                    for fedex in range(0,len(fielderrors)):
                        errmsg = fielderrors[fedex]
                        if errmsg == 'Select a valid choice. That choice is not one of the available choices.':
                            fielderrors[fedex] = 'Select a valid choice. Valid choices are {0}'.format(', '.join([x[1] for x in formset[formdex].fields[field].choices]))
            debug = formset.errors

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
            response = HttpResponse(content_type=content_type)
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
#            pfs = [ f.name for f in modelFields(myModel) if isinstance(f,related.RelatedField) and not maskField(f) ]
#            try:
#                results = results.prefetch_related(*pfs)
#            except AttributeError:
#                pass # probably got list-ified

        vname =  verbose_name(myModel)
        try:
            reqid = pkValue(reqlog)
        except  AttributeError:
            reqid = None

        templateargs = {'base': 'base.html',
                        'title': 'Search ' + vname,
                        'reqid': reqid,
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
        nolog = ['reqid', 'formset', 'axesform', 'results', 'resultsids', 'scores', 'displayFields']
        return renderfn(request, reqlog, template,
                        templateargs,
                        nolog=nolog,
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
        ret =[ jsonify(f,level=level-1) for f in obj.forms ]
        #for k in dir(obj):
        #    print(k,getattr(obj,k))
        #print(obj)
        return ret
    except AttributeError:
        pass

    try:
        #ret = jsonify(obj.fields)
        #for k in ['add_error', 'add_initial_prefix', 'add_prefix', 'as_expert_table', 'as_p', 'as_table', 'as_ul', 'auto_id', 'base_fields', 'changed_data', 'clean', 'data', u'declared_fields', 'empty_permitted', 'error_class', 'errors', 'fields', 'files', 'full_clean', 'has_changed', 'hidden_fields', 'initial', 'is_bound', 'is_multipart', 'is_valid', 'label_suffix', 'media', 'model', 'modelVerboseName', 'non_field_errors', 'prefix', 'visible_fields']:
         #   print(k,getattr(obj,k))
        return (obj.prefix,dict([('errors', jsonify(obj.errors,level=level-1)),
                                 ('fields', jsonify(obj.fields,level=level-1))]))
    except AttributeError:
        pass

    try:
        return dict([(str(k), jsonify(v,level=level-1)) for k,v in obj.items()])
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
            # stuff['choices'] = jsonify(list(getattr(obj,'choices')),level=level-1)
        return stuff
    except AttributeError:
        pass

    try:
        if isinstance(obj,(ErrorDict,ErrorList)):
            return obj
    except NameError:
        pass
        ## ErrorDict, ErrorList not defined

    if (level > 0):
        try:
            return dict([(f.name,jsonify(safegetattr(obj,f.name),level=level-1)) for f in modelFields(obj) if not maskField(f) or (f == pk(obj))])
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


def jsonify(obj,level=2):
    return jsonifier(obj,level=level)


def cleanQueryCache(timeout):
    """
    Remove entries exceeding timeout (in seconds)
    """
    curtime = datetime.datetime.now()
    timedout = []
    for k,v in queryCache.iteritems():
        if total_seconds(curtime - v[0]) > timeout:
            timedout.append(k)
    for k in timedout:
        del queryCache[k]


def getFieldValuesReal(request, searchModuleName, searchModelName, field,
                   soft=True,  queryGenerator=None):
    """
    get values from a search for just one field
    """

    starttime = datetime.datetime.now()
    reqlog = recordRequest(request)
    modelmodule = __import__('.'.join([searchModuleName, 'models'])).models
    myModel = getattr(modelmodule, searchModelName)
    myFields = [ x for x in modelFields(myModel) if not maskField(x) ]
    tmpFormClass = SpecializedForm(SearchForm, myModel,
                                   queryGenerator=queryGenerator)
    tmpFormSet = formset_factory(tmpFormClass)
    data = getDataFromRequest(request)
    soft = soft not in (False, 'False', 'exact')

    myField =  resolveField(myModel, field)

    try:
        formset = tmpFormSet(data)
    except ValidationError:
        formset = tmpFormSet()

    if formset.is_valid():
        pkName = pk(myModel).name

        query, hardCount, totalCount = queryLogic(myModel, formset, soft = soft, queryGenerator=queryGenerator)
        # if soft:
        #     query = getMatches(myModel, formsetToQD(formset), queryGenerator=queryGenerator)
        # else:
        #     query = getMatches(myModel, formsetToQD(formset), threshold=1, queryGenerator=queryGenerator)

        # print(str(objs.query))
        ## need to turn into list, as a query will get re-values()'d.
        qkey = str(query.query)
        cleanQueryCache(300)
        if (qkey in queryCache):
            cachetime, objs = queryCache[qkey]
        else:
            objs = list(query)
            queryCache[qkey] = (starttime, objs)

        if myField is None:
            dbobjs = [(pkValue(x), str(x)) for x in objs]
            objs = []
            for rank in range(len(dbobjs)):
                objs.append(dict([(pkName,dbobjs[rank][0]),("Name",dbobjs[rank][1]),("Rank",rank)]))
        else:
            if isinstance(myField,related.RelatedField):
                ## I think we are getting a mismatch with the rmap getattr
                ## resolved into objects, where appropriate, but in fact
                ## they may need to be ids sometimes
                rmap = dict([(x,getattr(x,myField.column)) for x in objs])
                relargs =  dict([(pk(myField.rel.to).name+'__in',
                                  set(rmap.values()))])
                ## also, should that really be .id or pkValue?
                ##relobjs = dict([(x.id, x) for x in myField.rel.to.objects.filter(**relargs)])
                relobjs = dict([(pkValue(x), x) for x in myField.rel.to.objects.filter(**relargs)])
                for x,relid in rmap.iteritems():
                    try:
                        setattr(x,myField.name,relobjs[relid])
                    except KeyError:
                        ## no relobjs[relid]!
                        setattr(x,myField.name,None)

                    # prefetch is not the way to go here, as we've
                    # already retrieved original query
                    # query = query.prefetch_related(myField)
                    # objs = list(query)
            objs = [dict([(pkName,pkValue(x)), (field,getattr(x,field))]) for x in objs]
            ##objs = list(objs.values(pkName, field))
            if isinstance(myField,related.RelatedField):
                # nameids = [x[field] for x in objs]
                # names = dict([(pkValue(r),str(r)) for r in myField.rel.to.objects.filter(pk__in=nameids)])
                for x in objs:
                    try:
                        x[field] = str(x[field])
                    except KeyError:
                        pass
    else:
        print(formset.errors)
        print("Not valid")
        objs = formset.errors

    dumps = json.dumps(objs, default=jsonify)

    return HttpResponse(dumps, content_type='application/json')


def getFieldValues(request, searchModuleName, searchModelName, field,
                   soft=True,  queryGenerator=None):
    try:
        return getFieldValuesReal(request, searchModuleName, searchModelName, field,
                              soft=soft,  queryGenerator=queryGenerator)
    except Exception:
        traceback.print_exc()

## queryGenerator is presumably irrelvant here because we aren't querying
## yet, just doing a form validation
def plotQueryResults(request, searchModuleName, searchModelName,
                     soft=True):
    """
    Plot the results of a query
    """
    # start = int(start)
    # end = int(end)
    reqlog = recordRequest(request)
    modelmodule = __import__('.'.join([searchModuleName, 'models'])).models
    myModel = getattr(modelmodule, searchModelName)
    myFields = [ x for x in modelFields(myModel) if not maskField(x) ]
    tmpFormClass = SpecializedForm(SearchForm, myModel)
    tmpFormSet = formset_factory(tmpFormClass)
    data = getDataFromRequest(request)
    soft = soft not in (False, 'False', 'exact')

    axesform = AxesForm(myFields, data)
    fieldDict = dict([ (x.name, x) for x in myFields ])
    timeFields = [fieldName
                  for fieldName, fieldVal in fieldDict.iteritems()
                  if isinstance(fieldVal, (DateField, TimeField))]

    try:
        formset = tmpFormSet(data)
        if formset.is_valid():
            ## a lot of this code mimics what is in searchChosenModel
            ## should figure out a way of centralizing instead of copying

    #        plotdata = []
    #
    #        objs, totalCount, hardCount = getMatches(myModel, formsetToQD(formset), soft, queryStart = start, queryEnd = end)
    #
    #        pfs = [ f.name for f in modelFields(myModel) if isinstance(f,related.RelatedField) and not maskField(f) ]
    #        try:
    #            objs = objs.prefetch_related(*pfs)
    #        except AttributeError:
    #            pass # probably got list-ified
    #
    #
    #        for x in objs:
    #            pdict = { pkName: x.pk }
    #            for fld in myFields:
    #                val = megahandler(safegetattr(x, fld.name, None))
    #                try:
    #                    pdict[fld.name] = val.name
    #                except AttributeError:
    #                    pdict[fld.name] = val
    #            plotdata.append(pdict)
    #        pldata = [str(x) for x in objs]
    #
    #        ## the following code determines if there are any foreign keys that can be selected, and if so,
    #        ## replaces the corresponding values (which will be ids) with the string representation
    #        seriesChoices = dict(axesform.fields['series'].choices)
    #
    #        seriesValues = dict([ (m.name, getRelated(m))
    #                        for m in myFields
    #                        if ((m.name in seriesChoices) and (m.rel is not None) )])
    #        for x in plotdata:
    #            for k in seriesValues.keys():
    #                if x[k] is not None:
    #                    try:
    #                        x[k] = seriesValues[k][x[k]]
    #                    except:  # pylint: disable=W0702
    #                        x[k] = str(x[k])  # seriesValues[k][seriesValues[k].keys()[0]]

            debug = []
            #totalCount = myModel.objects.filter(filters).count()
            # shownCount = len(pldata)
        else:
            debug = [(x, formset.errors[x]) for x in formset.errors]
    #        totalCount = None
    #        pldata = []
    #        plotdata = []
    #        objs = []
    except ValidationError as err:
        formset = tmpFormSet()
        debug = [("Query Error", "No query submitted- did you enter a URL instead of submitting a form?")]

    totalCount = None
    shownCount = None

    template = resolveSetting('XGDS_DATA_PLOT_TEMPLATES', myModel, 'xgds_data/plotQueryResults.html')
    return log_and_render(request, reqlog, template,
                          {'title': 'Plot ' + verbose_name(myModel),
                           'standalone': not GEOCAMUTIL_FOUND,
#                           'plotData': json.dumps(plotdata, default=jsonify),
#                           'labels': pldata,
                           'timeFields': json.dumps(timeFields),
                           'module': searchModuleName,
                           'model': searchModelName,
                           'pk': pk(myModel).name,
                           # 'start': start,
                           # 'end': end,
                           'soft': soft,
                           'debug': debug,
                           'count': totalCount,
                           'showncount': shownCount,
                           "formset": formset,
                           'axesform': axesform
                           },
                          nolog=['plotData', 'labels', 'formset', 'axesform'],
                          )


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
    myModel = apps.get_model(editModuleName, editModelName)
    tmpFormClass = SpecializedForm(EditForm, myModel)
    myFields = [x for x in modelFields(myModel) if not maskField(x) ]
    record = myModel.objects.get(pk=rid)
    retformat = getDataFromRequest(request).get('format', 'html')
    if (getDataFromRequest(request).get('fnctn',None) == 'edit'):
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
        return defaultPage('xgds_data_displayRecord', [editModuleName, editModelName, rid])
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



def chooseGroupModel(request, groupModuleName):
    """
    List the models in the module, so they can be selected for grouping
    """
    return chooseModel(request, groupModuleName, 'Search ' + groupModuleName,
                       'group', 'xgds_data_createCollection')


def createCollection(request, groupModuleName, groupModelName, expert=False):
    """
    create a collection of data
    """

    def actionRenderFn(request, groupeeModuleName, groupeeModelName, objs):
        coll = Collection.objects.create()
        coll.save()
        links = []
        if objs is not None:
            for inst in objs:
                ##links.append(GenericLink.objects.create(link=inst))
                links.append(GenericLink(link=inst,collection=coll))

        if len(links) > 0:
            glinks = GenericLink.objects.bulk_create(links)

        try:
            ## try any specialized edit first
            return HttpResponseRedirect(coll.get_edit_url())
        except AttributeError:
            return HttpResponseRedirect(reverse('xgds_data_editRecord', args=[moduleName(Collection), modelName(Collection), pkValue(coll)]))

    return selectForAction(request, groupModuleName, groupModelName,
                           'xgds_data_createCollection',
                           'Group Selected',
                           actionRenderFn,
                           expert=expert,
                           confirmed=True)


def getCollectionContents(request, rid):
    """
    Stuff in a collection
    """
    reqlog = recordRequest(request)
    record = Collection.objects.get(pk=rid)
    stuff = record.resolvedContents()
    retformat = getDataFromRequest(request).get('format', 'html')
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
    rerequest = reqlog.recreateRequest(request)
    view, args, kwargs = resolve(reqlog.path)
    kwargs['request'] = rerequest

    return view(*args, **kwargs)

@login_required
def instrumentDataImport(request):
    errors = None
    if request.method == 'POST':
        form = ImportInstrumentDataForm(request.POST, request.FILES)
        if form.is_valid():
            instrument = settings.SCIENCE_INSTRUMENT_DATA_IMPORTERS[
                int(form.cleaned_data["instrumentId"])]
            importFxn = instrument["importFunction"]
            return importFxn(instrument, request.FILES["sourceFile"],
                             form.cleaned_data["dataCollectionTime"],
                             form.getTimezone(), form.getResource())
        else:
            errors = form.errors
    return render(
        request,
        'xgds_data/importInstrumentData.html',
        {
            'form': ImportInstrumentDataForm(),
            'errorstring': errors
        },
    )
