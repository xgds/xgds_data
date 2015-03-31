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

from xgds_data.models import cacheStatistics
if cacheStatistics():
    from xgds_data.models import ModelStatistic


def tableSize(model):
    """
    Get table size either from cache or live
    """
    tsize = None
    if cacheStatistics():
        countEst = ModelStatistic.objects.filter(model=model.__name__).filter(field=None).filter(statistic="count")
        if (countEst.count() > 0):
            print("Guessed")
            tsize = int(countEst[0].value)
    if tsize is None:
        tsize = model.objects.count()
    return tsize


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
