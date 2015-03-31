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
        args = []
        for a in data.keys():
            args = args + [RequestArgument(request=reqlog, name=a, value=v) for v in data.getlist(a)]
        # args = [ RequestArgument(request=reqlog, name=key, value=data.get(key)) for key in data ]
        RequestArgument.objects.bulk_create(args)

        return reqlog
    else:
        return None


def getListItemProperty(obj, prop):
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
                                  # fclass=str(results[r - 1]['__class__']),
                                  # fid=results[r - 1][  results[r - 1]['__class__']._meta.pk.name ] )
                                  fclass=str(getListItemProperty(results[r - 1], '__class__')),
                                  fid=getListItemProperty(results[r - 1],
                                                          getListItemProperty(results[r - 1], '__class__')._meta.pk.name))

                     for r in ranks]
            try:
                ResponseList.objects.bulk_create(items)
            except ValueError as e:
                print(e)


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
        reslog = ResponseLog.create(request=reqlog, template=template)
        reslog.save()

        args = []
#        for a in rendargs.keys():
#            args = args + [ ResponseArgument(response=reslog, name=key, value=rendargs.get(key).__str__()[:1024]) \
#                            for key in rendargs.getlist(a) if nolog.count(key) == 0 ]
        for key in rendargs:
            if nolog.count(key) == 0:
                try:
                    # check if an object is a list or tuple (but not string)
                    # http://stackoverflow.com/questions/1835018/python-check-if-an-object-is-a-list-or-tuple-but-not-string
                    assert not isinstance(rendargs.get(key), basestring)
                    args = args + [ResponseArgument(response=reslog, name=key, value=str(v)[:1024]) for v in rendargs.get(key)]
                except (TypeError, AssertionError):
                    # not iterable
                    args = args + [ResponseArgument(response=reslog, name=key, value=str(rendargs.get(key))[:1024])]
#        args = [ ResponseArgument(response=reslog, name=key, value=rendargs.get(key).__str__()[:1024]) \
#                  if nolog.count(key) == 0 ]

        ResponseArgument.objects.bulk_create(args)
        if listing:
            recordList(reslog, listing)
    return render(request, template, rendargs, content_type=content_type)
