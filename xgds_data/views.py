# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import re

from django.shortcuts import render_to_response
from django.http import HttpResponseNotAllowed, HttpResponseRedirect, HttpResponseForbidden, Http404
from django.template import RequestContext

from xgds_data.models import getModelByName
from xgds_data.forms import QueryForm
from xgds_data import settings


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
        mostRecentFirst = form.cleaned_data['mostRecentFirst']

        prefix = 'SELECT * FROM %s ' % tableName
        if mostRecentFirst and timestampField:
            prefix += 'ORDER BY %s DESC ' % timestampField
        sqlQuery = prefix + userQuery

        # escape % signs, interpreted by Django raw() as template format
        escapedSqlQuery = re.sub(r'%', '%%', sqlQuery)
        styledSql = prefix + '<span style="color: blue; font-weight: bold">%s</span>' % userQuery

        matches = list(model.objects.raw(escapedSqlQuery))

        result = {
            'sql': styledSql,
            'summary': '%s matches' % len(matches),
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
