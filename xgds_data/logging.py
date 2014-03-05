# __BEGIN_LICENSE__
# Copyright (C) 2008-2013 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from math import floor, log

from django.shortcuts import render

from xgds_data import settings
from xgds_data.logconfig import logEnabled

if logEnabled():
    from xgds_data.models import (RequestLog,
                                  RequestArgument,
                                  ResponseLog,
                                  ResponseArgument,
                                  ResponseList)


def recordRequest(request):
    """
    Logs the request in the database
    """
    if logEnabled():
        data = request.REQUEST
        reqlog = RequestLog.create(request)
        reqlog.save()
        for key in data:
            arg = RequestArgument.objects.create(request=reqlog, name=key, value=data.get(key))
            arg.save()
        return reqlog
    else:
        return None


def getListItemProperty(obj,prop):
    """
    Record list might get either instances or dicts with instance contents, so use this 
    """
    try:
        return obj[prop]
    except TypeError:
        return getattr(obj, prop)


def recordList(reslog, results):
    """
    Logs a ranked list of results
    """
    if logEnabled():
        if results:
            ranks = range(1, min(201, len(results)))
            ranks.extend([(2 ** p) for p in range(8, 1 + int(floor(log(len(results), 2))))])
            ranks.append(len(results))
            items = [ResponseList(response=reslog,
                                  rank=r,
#                                  fclass=str(results[r - 1]['__class__']),
#                                  fid=results[r - 1][  results[r - 1]['__class__']._meta.pk.name ] )
                                  fclass=str(getListItemProperty(results[r - 1],'__class__')),
                                  fid=getListItemProperty( results[r - 1], \
                                         getListItemProperty(results[r - 1],'__class__')._meta.pk.name ) )

                     for r in ranks]
            ResponseList.objects.bulk_create(items)


def log_and_render(request, reqlog, template, rendargs,
                   content_type=settings.DEFAULT_CONTENT_TYPE,
                   nolog=None,
                   listing=None):
    """
    Logs the response in the database and returns the rendered page
    """
    if nolog is None:
        nolog = []
    if logEnabled():
        reslog = ResponseLog.objects.create(request=reqlog, template=template)
        for key in rendargs:
            if nolog.count(key) == 0:
                ResponseArgument.objects.create(response=reslog, name=key, value=rendargs.get(key).__str__()[:1024])
        if listing:
            recordList(reslog, listing)
    return render(request, template, rendargs, content_type=content_type)
