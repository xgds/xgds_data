#!/usr/bin/env python
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

import os
import sys
import django
import datetime
import pytz
# django.setup()

from django.apps import apps
from django.db.models import (StdDev, fields)
from xgds_data.models import cacheStatistics
from xgds_data.introspection import (qualifiedModelName, isAbstract,
                                     modelFields, isNumeric)
from django.conf import settings
if cacheStatistics():
    from xgds_data.models import ModelStatistic

tableCounts = dict()
tableCountsAge = dict()
fieldCounts = dict()
fieldCountsAge = dict()

def timeout():
    """
    Get the timeout for the cache
    """
    try:
        return settings.XGDS_DATA_CACHE_TIMEOUT
    except AttributeError:
        return 60


def getStatistic(model, field, stat, statFn):
    """
    whatever it is
    """
    qname = qualifiedModelName(model)
    statVal = None
    if cacheStatistics():
        try:
            statVal = ModelStatistic.objects.filter(model=qname,field=field,statistic=stat)[0].value
        except IndexError:
            pass # no results
    if statVal is None:
        statVal = statFn()
        if cacheStatistics():
            timestamp = datetime.datetime.now(pytz.utc)
            ModelStatistic.objects.create(recorded = timestamp,
                                          model = qname,
                                          field = field,
                                          statistic = stat,
                                          value = statVal)
            ## remove old entries
            ModelStatistic.objects.filter(recorded__lt=timestamp,
                                          model = qname,
                                          field = field,
                                          statistic = stat).delete()

    return statVal


def tableSize(model):
    """
    Get table size either from cache or live
    """
    return getStatistic(model, '', 'count', model.objects.all().count)


def fieldSize(field, itemCount, maxItemCount, maxFieldCount):
    """
    Get table size either from cache or live
    """
    estCount = None
    try:
        if timeout() is not None:
            maxage = datetime.timedelta(seconds = timeout())
            aged = datetime.datetime.now(pytz.utc) - fieldCountsAge[field]
            if (aged < maxage):
                estCount = fieldCounts[field]
        else:
            estCount = fieldCounts[field]
    except KeyError: # not in cache yet
        pass

    if estCount is None:
        try:
            estCount = tableSize(field.rel.to)
        except AttributeError:
            if (itemCount < maxItemCount):
                estCount = itemCount
            elif (itemCount < maxFieldCount):
                estCount = field.model.objects.values(field.name).order_by().distinct().count()

        fieldCountsAge[field] = datetime.datetime.now(pytz.utc)
        fieldCounts[field] = estCount
    return estCount


def nextPercentile(model, fld, val, kind):
    """
    Returns the next percentile, else none
    """
    if (val is None):
        return None
    else:
        pctiles = ModelStatistic.objects.filter(model=model.__name__).filter(field=fld).values('value')
        if kind == 'lt':
            pctiles = pctiles.filter(value__lt=val).order_by('-value')[:1]
        elif kind == 'lte':
            pctiles = pctiles.filter(value__lte=val).order_by('-value')[:1]
        elif kind == 'gt':
            pctiles = pctiles.filter(value__gt=val).order_by('value')[:1]
        elif kind == 'gte':
            pctiles = pctiles.filter(value__gte=val).order_by('value')[:1]
        else:
            raise Exception("Don't understand percentile request on %s" % kind)

        if len(pctiles) > 0:
            return pctiles[0]['value']
        else:
            return None


def segmentBounds(model, fld, loend, hiend):
    """
    Finds the canned segment this area falls into
    """
    if (loend != hiend):
        raise Exception("I am not emotionally prepared for this inevitability")

    if loend is not None:
        lobound = nextPercentile(model, fld, loend, 'lte')
    else:
        lobound = nextPercentile(model, fld, hiend, 'lte')
    if hiend is not None:
        hibound = nextPercentile(model, fld, hiend, 'gt')
    else:
        hibound = nextPercentile(model, fld, loend, 'gt')

    return [lobound, hibound]

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        print("Usage: DataStatistics.py moduleName [modelName] [statistic]")
    else:
        moduleName = sys.argv[1]

    if len(sys.argv) == 3:  # 2nd arg (if provided) is the name of a model
        models = apps.get_model(moduleName, sys.argv[2])
    else:
        models = [m for m in apps.get_app_config(moduleName).get_models()]

    try:
        statistic = sys.argv[3]
    except IndexError:
        statistic = 'count'

    for m in models:
        if not isAbstract(m):
            if statistic == 'count':
                print(m, getStatistic(m, '', 'count', m.objects.all().count))
            elif statistic == 'StdDev':
                for f in modelFields(m):
                    if isNumeric(m, f):
                        fn = lambda: m.objects.all().aggregate(StdDev(f.name)).values()[0]
                        print(m, f, getStatistic(m, f.name, 'StdDev', fn))

