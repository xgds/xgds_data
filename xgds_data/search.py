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

import re
import datetime
import calendar
import pytz

from math import floor, log10, pow as mpow  # shadows built-in pow()
from operator import itemgetter

#from django import forms
from django.db import connection
from django.db.models import (Q, Field, fields, StdDev)
from django.db.models.fields import (PositiveIntegerField, PositiveSmallIntegerField)
#from django.contrib.contenttypes.generic import GenericForeignKey
from django.db.models import (Min, Max)
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from xgds_data.introspection import (modelFields, resolveField, maskField,
                                     isAbstract, concreteDescendants,
                                     pk, db_table, fullid, accessorDict,
                                     resolveModel, fieldModel, parentField)
from xgds_data.models import (cacheStatistics, VirtualIncludedField)
if cacheStatistics():
    from xgds_data.models import ModelStatistic
from xgds_data.DataStatistics import (tableSize, segmentBounds, nextPercentile,
                                      getStatistic)
from xgds_data.utils import (total_seconds, handleFunnyCharacters)

sdCache = dict()

def timer(t, msg):
    newtime = datetime.datetime.now(pytz.utc)
    print([str(newtime - t), str(msg)])
    return newtime


def walkQ(qstmt):
    """
    A somewhat aborted attempt to piece together the corresponding sql from a Q object
    """
    if isinstance(qstmt, Q):
        con = ' ' + qstmt.connector + ' '
        return ('(' +
                con.join([walkQ(x)
                          for x in qstmt.children]) +
                ')')
    elif isinstance(qstmt, tuple):
        subjpred, obj = qstmt
        doubleunderscorepos = subjpred.rfind('__')
        if (doubleunderscorepos):
            subj = subjpred[:(doubleunderscorepos)]
            pred = subjpred[(doubleunderscorepos + 2):]
            predSubs = {
                'lt': '<',
                'gt': '>',
                'gte': '>=',
                'lte': '<=',
                'in': 'IN',
                'exact': '=',
                'icontains': 'ILIKE'
            }
            if pred in predSubs:
                pred = predSubs[pred]
            if not isinstance(obj, (int, long, float, complex)):
                obj = '"' + str(obj) + '"'
            return '(' + ' '.join([subj, pred, str(obj)]) + ')'
        else:
            print("Cannot parse Q statement: " + str(qstmt))
    else:
        print("Encountered unexpected type" + qstmt.__class__)
        return '1 != 1'


def isPostgres():
    """
    Check to see if the backend is postgres, not mysql
    """
    return settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql_psycopg2'


def virtualArguments(model, qdatas, soft=True):
    """
    Gets the portion of a query that applies to virtual fields
    """
    mfields = dict([(f.name, f) for f in modelFields(model)])
    fdict = dict()
    for qd in qdatas:
        for fieldname, fieldval in qd.iteritems():
            if (fieldname.endswith('_lo') or fieldname.endswith('_hi')):
                fieldname = fieldname[:-3]

            mf = mfields.get(fieldname)
            try:
                if (mf is not None) and (fieldval is not None):
                    for tm in mf.throughModels():
                        if tm not in fdict:
                            fdict[tm] = set()
                        fdict[tm].add(mf)
            except AttributeError:
                pass # not a virtual field
    return(fdict)


def queryArgChain(model, qcomplexarg):
    """
    """
    qchain = []
    for qa in qcomplexarg.split('__'):
        ad = accessorDict(model)
        ## "relation" because it's not necessarily field, could be inverse
        ## also need to test with many to many fields
        relation = ad[qa]
        qchain.append(relation)
        try:
            model = relation.rel.to
        except AttributeError:
            model = relation.model

    return qchain


## TODO: does not appear to do anything with hard VirtualIncludedField
## constraints, maybe as they show up as generic
def makeFilters(model, qdatas, soft=True):
    """
    Helper for getMatches; figures out restrictions given a query parameters
    """
    filters = None
    mfields = dict([(f.name, f) for f in modelFields(model)])
    ## forms are interpreted as internally conjunctive, externally disjunctive
    for qd in qdatas:
        subfilter = Q()
        for fieldname in qd:
            if fieldname.endswith('_operator'):
                basename = fieldname[:-(len('_operator'))]
                qargs = queryArgChain(model, basename)
                modelfieldname = qargs[0].name
                mf = mfields.get(modelfieldname)
                if mf is None:
                    print("No match for ",modelfieldname)
                else:
                    operator = qd[basename + '_operator']
                    try:
                        loqval = handleFunnyCharacters(qd[basename + '_lo'])
                        hiqval = handleFunnyCharacters(qd[basename + '_hi'])
                        rangeQuery = True
                    except KeyError:
                        qval = handleFunnyCharacters(qd[basename])
                        rangeQuery = False

                    if isinstance(mf, VirtualIncludedField):
                        fieldname = mf.throughfield_name + '__' + fieldname
                        ## this branch looks broken - don't we need to do something?
                    else:
                        clause = None
                        negate = False
                        terminalfield = qargs[-1]

                        if rangeQuery:
                            if soft and (operator == 'IN~'):
                                ## this isn't a restriction, so ignore
                                pass
                            else:
                                negate = operator == 'NOT IN'
                                if (loqval is not None and hiqval is not None):
                                    if loqval > hiqval:
                                        ## hi and lo are reversed, assume that is a mistake
                                        swap = loqval
                                        loqval = hiqval
                                        hiqval = swap

                                    ## these aren't simple Q objects so don't set clause variable
                                    if negate:
                                        negate = False # handle negation now
                                        subfilter &= (Q(**{basename + '__lt': loqval}) |
                                                      Q(**{basename + '__gt': hiqval}))
                                    else:
                                        subfilter &= (Q(**{basename + '__gte': loqval}) &
                                                      Q(**{basename + '__lte': hiqval}))
                                elif loqval is not None:
                                    clause = Q(**{basename + '__gte': loqval})
                                elif hiqval is not None:
                                    clause = Q(**{basename + '__lte': hiqval})
                                else:
                                    pass # both are None, no restriction
                        elif qval is None:
                            pass
                        elif isinstance(terminalfield, fields.related.ManyToManyField):
                            negate = operator == 'NOT IN'
                            try:
                                assert isinstance(qval, (list, tuple))
                                assert not isinstance(qval, basestring)
                                clause = Q(**{basename + '__in': qval})
                            except AssertionError:
                                ## needs to be iterable
                                clause = Q(**{basename + '__in': [qval]})
                        elif isinstance(terminalfield, (fields.related.ForeignKey,
                                                        fields.related.OneToOneField)):
                            negate = operator == '!='
                            clause = Q(**{basename + '__exact': qval})
                        elif re.match("\s*$", qval) or (operator == '=~'):
                            pass
                        elif qval == 'None' and isinstance(terminalfield, fields.NullBooleanField):
                            pass
                        else:
                            negate = (operator == '!=')
                            if qval == 'True':
                                ## True values appear to be represented as numbers greater than 0
                                clause = Q(**{basename + '__gt': 0})
                            elif qval == 'False':
                                ## False values appear to be represented as 0
                                clause = Q(**{basename + '__exact': 0})
                            else:
                                clause = Q(**{basename + '__icontains': qval})
                        if clause:
                            if negate:
                                subfilter &= ~clause
                            else:
                                subfilter &= clause

        if filters:
            filters |= subfilter
        else:
            filters = subfilter
    return filters


def baseScore(fieldRef, lorange, hirange):
    """
    provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
    """
    timeConversion = False
    if isinstance(lorange, datetime.datetime):
        timeConversion = True
        lorange = calendar.timegm(lorange.timetuple())
        ##lorange = time.mktime(lorange.timetuple())
    if isinstance(hirange, datetime.datetime):
        timeConversion = True
        hirange = calendar.timegm(hirange.timetuple())
        ##hirange = time.mktime(hirange.timetuple())
    ## perhaps could swap lo, hi if lo > hi
    if (timeConversion):
        if isPostgres():
            fieldRef = "EXTRACT(EPOCH FROM ({0} AT TIME ZONE 'UTC'))".format(fieldRef)
        else:
            ## UGH: mysql's UNIX_TIMESTAMP always assumes system timezone, but we are storing UTC
            ## Solution: convert to system time zone and then get unix timestamp
            fieldRef = 'UNIX_TIMESTAMP(CONVERT_TZ({0},"+00:00",@@session.time_zone))'.format(fieldRef)

    if lorange == hirange:
        return "abs({0}-{1})".format(fieldRef, lorange)
    elif lorange == 'min':
        return "greatest(0,{0}-{1})".format(fieldRef, hirange)
    elif hirange == 'max':
        return "greatest(0,{1}-{0})".format(fieldRef, lorange)
    else:
        ##return "greatest(0,least({1}-{0},{0}-{2}))".format(field, lorange, hirange)
        return "greatest(0,{1}-{0},{0}-{2})".format(fieldRef, lorange, hirange)


def randomSample(model, expression, size, offset=None, limit=None):
    """
    Selects a random set of records, assuming even distibution of ids; not very Django-y
    """
    table = db_table(model)
    ##pkname = dbFieldRef(pk(model)) # blows up the USING clause, apparently
    pkname = pk(model).attname
    randselect = 'SELECT {1} from {0} WHERE {2} IS NOT NULL ORDER BY RAND() limit {3}'.format(table, pkname, expression, size)
    ## turns out mysql has a direct way of selecting random rows; below is a more complicated way that requires
    ## consecutive ids, etc
    #randselect = '(SELECT CEIL(RAND() * (SELECT MAX({1}) FROM {0})) AS {1} from {0} limit {2})'.format(table, pkname, size)
    if offset is None or limit is None:
        sql = ('select {2} as score from {0} JOIN ({3}) AS r2 USING ({1}) order by score;'
               .format(table, pkname, expression, randselect))
    else:
        sql = ('select {2} as score from {0} JOIN ({3}) AS r2 USING ({1}) order by score limit {4},{5};'
               .format(table, pkname, expression, randselect, offset, limit))
    cursor = connection.cursor()
##    runtime = datetime.datetime.now(pytz.utc)
    cursor.execute(sql)
##    runtime = timer(runtime, "<<< inner random sample >>>")
    return cursor.fetchall()


def sdRandomSample(model, expression, size):
    """
    Selects a random set of records, assuming even distibution of ids; not very Django-y
    """
    table = db_table(model)
    ##pkname = dbFieldRef(pk(model)) # blows up the USING clause, apparently
    pkname = pk(model).attname
    randselect = 'SELECT {1} FROM {0} WHERE {2} IS NOT NULL ORDER BY RAND() LIMIT {3}'.format(table, pkname, expression, size)
    ## turns out mysql has a direct way of selecting random rows; below is a more complicated way that requires
    ## consecutive ids, etc
    sql = ('SELECT STDDEV({2}) AS sd FROM {0} JOIN ({3}) AS r2 USING ({1}) ORDER BY sd;'
               .format(table, pkname, expression, randselect))
    cursor = connection.cursor()
##    runtime = datetime.datetime.now(pytz.utc)
    cursor.execute(sql)
##    runtime = timer(runtime, "<<< inner random sample >>>")
    return cursor.fetchall()[0]


def countApproxMatches(model, scorer, maxSize, threshold):
    """
    Take a guess as to how many records match by examining a random sample
    """
    cpass = 0.0
    sample = randomSample(model, scorer, 10000)
    if len(sample) == 0:
        return 0
    else:
        for x in sample:
            if x[0] >= threshold:
                cpass = cpass + 1
        ##query = query[0:round(maxSize * cpass / len(sample))]
        resultCount = maxSize * cpass / len(sample)
        ## make it look approximate
        if resultCount > 10:
            resultCount = int(round(resultCount / mpow(10, floor(log10(resultCount))))
                              * mpow(10, floor(log10(resultCount))))
        elif resultCount > 0:
            resultCount = 10
        return resultCount


def medianEval(model, expression, size):
    """
    Quick mysql-y way of estimating the median from a sample
    """
    count = model.objects.count()
    if count == 0:
        return None
    else:
        sampleSize = min(size, 1000)
        result = ()
        triesLeft = 100
        ## not sure why, but sometimes nothing is returned
        while (len(result) == 0) and (triesLeft > 0):
            ## trying to pick the middle in advance is too risky because we may not get back as many as expected
            ## (for instance, when the field value is sometimes NULL)
            ## result = randomSample(model, expression, sampleSize), sampleSize / 2, 1)
            result = randomSample(model, expression, sampleSize)
            triesLeft = triesLeft - 1
        if len(result) == 0:
            return None
        else:
            return result[int((len(result) - 1) / 2)][0]


# def medianRangeEval(model, field, lorange, hirange, size, fieldRef):
#     """
#     Quick mysql-y way of estimating the median from a range sample
#     """
#     if cacheStatistics():
#         ## I'm sure there's a great reason why \d is not working like [0-9] for me, but I don't understand it
#         ## So, clunky looking regex
#         percentiles = ModelStatistic.objects.filter(model=model.__name__).filter(field=field.name).filter(statistic__regex=r'p[0-9]+$')
#         if (percentiles.count() > 0):
#             if lorange == hirange:
#                 vals = sorted([abs(x.value - lorange) for x in percentiles])
#             elif lorange is None or lorange == 'min':
#                 vals = sorted([max(0, x.value - hirange) for x in percentiles])
#             elif hirange is None or hirange == 'max':
#                 vals = sorted([max(0, lorange - x.value) for x in percentiles])
#             else:
#                 vals = sorted([max(0, lorange - x.value, x.value - hirange) for x in percentiles])
#             ##print('Guessed')
#             return(vals[int(round(len(vals) * 0.5)) - 1])
#     ## if we haven't returned a value already
#     ##print('NOT Guessed')
#     if isPostgres():
#         fname = field.name
#         dataranges = model.objects.aggregate(Min(fname), Max(fname))
#         datamin = dataranges[fname + '__min']
#         datamax = dataranges[fname + '__max']
#         if (isinstance(datamin, datetime.datetime) and (datamin.tzinfo is None)):
#             datamin = datamin.replace(tzinfo=pytz.utc)
#         if (isinstance(datamax, datetime.datetime) and (datamax.tzinfo is None)):
#             datamax = datamax.replace(tzinfo=pytz.utc)

#         if (lorange == 'min'):
#             lorange = None
#         if (hirange == 'max'):
#             hirange = None

#         ## odd formulation for an average works with datetimes, too
#         datamid = datamin + (datamax - datamin) / 2
#         if (hirange is not None) and (hirange < datamin):
#             retv = datamid - hirange
#         elif (lorange is not None) and (lorange > datamax):
#             retv = lorange - datamid
#         else:
#             if (lorange is None) or (lorange < datamin):
#                 lorange = datamin
#             if (hirange is None) or (hirange > datamax):
#                 hirange = datamax

#             belowweight = lorange - datamin
#             inweight = hirange - lorange
#             aboveweight = datamax - hirange

#             curweight = belowweight + inweight + aboveweight
#             halfweight = curweight / 2

#             curweight = curweight - inweight
#             if (curweight <= halfweight):
#                 ## half or more are score 0, so that's the median
#                 return 0
#             curweight = curweight - 2 * min(belowweight, aboveweight)
#             if (curweight <= halfweight):
#                 ## excess is the overshoot... back up to 50%
#                 excess = halfweight - curweight
#                 if belowweight < aboveweight:
#                     retv = lorange - (datamin + excess / 2)
#                 else:
#                     retv = (datamax - excess / 2) - hirange
#             else:
#                 if belowweight < aboveweight:
#                     retv = datamid - hirange
#                 else:
#                     retv = lorange - datamid

#         if isinstance(retv, datetime.timedelta):
#             retv = total_seconds(retv)

#         return retv
#     else:
#         return medianEval(model, baseScore(fieldRef, lorange, hirange), size)


def shifted_data_variance(data):
    """
    Stable variance calculation lifted from http://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Computing_shifted_data
    """
    if len(data) == 0:
        return 0
    K = data[0]
    n = 0
    Sum = 0
    Sum_sqr = 0
    for x in data:
        n = n + 1
        Sum += x - K
        Sum_sqr += (x - K) * (x - K)
    variance = (Sum_sqr - (Sum * Sum)/n)/(n - 1)
    # use n instead of (n-1) if want to compute the exact variance of the given data
    # use (n-1) if data are samples of a larger population
    return variance


def sdEval(model, expression, size):
    """
    Quick mysql-y way of estimating the median from a sample
    """
    if cacheStatistics():
        fn = lambda: model.objects.all().aggregate(StdDev(expression)).values()[0]
        return getStatistic(model, expression, 'StdDev', fn)
    try:
        return sdCache[model][expression]
    except KeyError:
        count = model.objects.count()
        if count == 0:
            ans= None
        else:
            sampleSize = min(size, 1000)
            result = ()
            triesLeft = 100
            ## not sure why, but sometimes nothing is returned
            while (len(result) == 0) and (triesLeft > 0):
                result = sdRandomSample(model, expression, sampleSize)
                triesLeft = triesLeft - 1
                if len(result) == 0:
                    ans = None
                else:
                    ans = result[0]
        # sdCache[model] = ans
        try:
            sdCache[model][expression] = ans
        except KeyError:
            sdCache[model] = dict()
            sdCache[model][expression] = ans
        return ans


def scaleEval(model, field, lorange, hirange, size, fieldRef):
    """
    Quick mysql-y way of estimating the median from a range sample
    """
    if cacheStatistics():
        ## I'm sure there's a great reason why \d is not working like [0-9] for me, but I don't understand it
        ## So, clunky looking regex
        percentiles = ModelStatistic.objects.filter(model=model.__name__).filter(field=field.name).filter(statistic__regex=r'p[0-9]+$')
        if (percentiles.count() > 0):
            return shifted_data_variance([x.value for x in percentiles])

    ## if we haven't returned a value already
    ##print('NOT Guessed')
    if isPostgres():
        ## postgres doesn't do random samples
        fname = field.name
        dataranges = model.objects.aggregate(Min(fname), Max(fname))
        datamin = dataranges[fname + '__min']
        datamax = dataranges[fname + '__max']
        if (isinstance(datamin, datetime.datetime) and (datamin.tzinfo is None)):
            datamin = datamin.replace(tzinfo=pytz.utc)
        if (isinstance(datamax, datetime.datetime) and (datamax.tzinfo is None)):
            datamax = datamax.replace(tzinfo=pytz.utc)

        if datamax == datamin:
            ## also handles case when both are None
            drange = 0
        else:
            drange = datamax-datamin
        if isinstance(drange, datetime.timedelta):
            drange = total_seconds(drange)

        ## assume its uniformly distributed, i.e., sd of uniform distribution
        retv = (1/(12**(0.5)))*drange


        #print(datamin, datamax, datamax - datamin, retv)
        return retv
    else:
        return sdEval(model, field.name, size)
        #return sdEval(model, baseScore(fieldRef, lorange, hirange), size)


def dbFieldRef(field):
    """
    return the alias for this field in the database query
    """
    ##if isinstance(field, VirtualIncludedField):
    try:
        tableName = db_table(field.targetFields()[0].model)
        fieldName = field.name
    except (IndexError, AttributeError):
    ##else:
        tableName = db_table(field.model)
        fieldName = field.column
    if isPostgres():
        ## not so sure about this... perhaps only sometimes?
        tableName = '"' + tableName + '"'
        fieldName = '"' + fieldName + '"'

    return tableName + '.' + fieldName


def dbFieldTable(field):
    """
    return the alias for this field in the database query
    """
    return db_table(fieldModel(field))


def autoweight(model, field, lorange, hirange, tblSize):
    """
    Would weight automatically, but isn't that magical yet
    """
    ## Yuk ... need to convert if field is unsigned
    # unsigned = False
    # if isinstance(field, (PositiveIntegerField, PositiveSmallIntegerField)):
    #     unsigned = True
    # ## Add table designation to properly resolve a field name that has another SQL interpretation
    # ## (for instance, a field name 'long')
    # fieldRef = dbFieldRef(field)
    # if (unsigned):
    #     fieldRef = "cast({0} as SIGNED)".format(fieldRef)
    # median = medianRangeEval(field.model, field, lorange, hirange, tblSize, fieldRef)
    # return (1+median)/2
    return 1


def scoreNumeric(model, field, lorange, hirange, tsize):
    """
    provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
    """
    ## Yuk ... need to convert if field is unsigned
    unsigned = False
    if isinstance(field, (PositiveIntegerField, PositiveSmallIntegerField)):
        unsigned = True
    ## Add table designation to properly resolve a field name that has another SQL interpretation
    ## (for instance, a field name 'long')
    fieldRef = dbFieldRef(field)
    if (unsigned):
        fieldRef = "cast({0} as SIGNED)".format(fieldRef)
    # median = medianEval(field.model, baseScore(fieldRef, lorange, hirange), tsize)
    try:
        tf = field.targetFields()[0]
        scale = scaleEval(tf.model, tf, lorange, hirange, tsize, fieldRef)
    except (IndexError,AttributeError):
        scale = scaleEval(model, field, lorange, hirange, tsize, fieldRef)
    if isPostgres():
        nullcheck ="CAST(({0} IS NOT NULL) AS INT)".format(fieldRef)
    else:
        nullcheck ="({0} IS NOT NULL)".format(fieldRef)
    if scale is None:
        return '1'
    elif scale == 0:
        ## would get divide by zero with standard formula below
        ## defining 0/x == 0 always, limit of standard formula leads to special case for 0, below.
        retv = "({0} = {1})".format(baseScore(fieldRef, lorange, hirange), scale)
        if isPostgres():
            retv = "CAST({0} AS INT)".format(retv)
    else:
        retv = "{1}/({1} + {0})".format(baseScore(fieldRef, lorange, hirange), scale)
    return "{0} * {1}".format(nullcheck,retv)


def desiredRanges(qdatas):
    """
    Pulls out the approximate (soft) constraints from the form
    """
    desiderata = dict()
    ## frms are interpreted as internally conjunctive, externally disjunctive
    for qd in qdatas:
        for field in qd:
            if (qd[field] is not None) and (field.endswith('_operator')):
                base = field[:-9]
                operator = qd[field]
                if operator == 'IN~':
                    loval = qd[base + '_lo']
                    try:
                        loval = handleFunnyCharacters(loval)
                    except AttributeError:
                        pass
                    hival = qd[base + '_hi']
                    try:
                        hival = handleFunnyCharacters(hival)
                    except AttributeError:
                        pass
                    if loval in (None, 'None'):
                        loval = 'min'
                    if hival in (None, 'None'):
                        hival = 'max'
                    if ((loval != 'min') and (hival != 'max') and (loval > hival)):
                    ## hi and lo are reversed, assume that is a mistake
                        loval, hival = hival, loval
                    if ((loval != 'min') or (hival != 'max')):
                        desiderata[base] = [loval, hival]
                elif operator == '=~':
                    print('what is ', operator)
                else:
                    pass
    return desiderata


# def ishard(frms):
#     """
#     Does the query lack soft constraints?
#     """
#     return (len(desiredRanges(frms)) == 0)


def sortFormula(model, qdatas):
    """
    Helper for searchChosenModel; comes up with a formula for ordering the results
    """
    return sortFormulaRanges(model, desiredRanges(qdatas))


def totalweight(model, qdatas):
    """
    Counts how many ranges count against this model
    """
    desiderata = desiredRanges(qdatas)
    tw = 0
    for b in desiderata.keys():
        field = resolveField(model, b)
        if (field is None) or isinstance(field, VirtualIncludedField):
            pass
        else:
            tw = tw + 1
    return tw


def sortFormulaRanges(model, desiderata):
    """
    Helper for searchChosenModel; comes up with a formula for ordering the results
    """
    if (len(desiderata) > 0):
        tsize = tableSize(model)
#        weights = dict([(b, autoweight(model, resolveField(model, b), desiderata[b][0], desiderata[b][1], tsize)) \
#                              for b in desiderata.keys()])
        # totalweight = len(desiderata)
#        for w in weights.values():
#            totalweight = totalweight + w
        scores = dict()
        for b in desiderata.keys():
            field = resolveField(model, b)
            if (field is None) or isinstance(field, VirtualIncludedField):
                pass
            else:
                scores[b] = scoreNumeric(model, field, desiderata[b][0], desiderata[b][1], tsize)
        if len(scores) == 0:
            return 1
        else:
            formula = ' + '.join([x for x in scores.itervalues()])
            return '({0})/{1} '.format(formula, len(scores))  # scale to have a max of 1
    else:
        return 1


def sortThreshold():
    """
    Guess on a good threshold to cutoff the search results
    """
    ## rather arbitrary cutoff, which would return 30% of results if scores are uniform
    return 0.7


def pageLimits(page, pageSize):
    """
    bla
    """
    return ((page - 1) * pageSize, page * pageSize)


def virtualProcessing(myModel, qdatas, query, gargs, threshold):
    """
    Querying on virtual included fields makes life difficult. Returns a list.
    """
    gweights = dict()
    for gmodel, gfs in gargs.iteritems():
        for gfield in gfs:
            # print(gfield,gfield.throughModels(),gfield.targetFields(),gfield.model,gfield.throughfield_name,gfield.name,gfield.verbose_name)
            gweights[gfield] = totalweight(gmodel, qdatas)

    allthroughfields = set()
    scales = dict()
    hards = dict()
    desiderata = desiredRanges(qdatas)
    for gfs in gargs.values():
        for gf in gfs:
            allthroughfields.add(gf.throughfield_name)
            gmodel = gf.throughModels()[0]
            gfield = gf.targetFields()[0]
            try:
                loend, hiend = desiderata[gfield.name]
                tsize = tableSize(gmodel)
                scales[gfield.name] = scaleEval(gmodel, gfield, loend, hiend, tsize, dbFieldRef(gfield))
            except KeyError:
                # hard constraint- lame hack
                for qd in qdatas:
                    oper = qd[gfield.name+'_operator']
                    try:
                        loend = qd[gfield.name]
                        hiend = qd[gfield.name]
                    except KeyError:
                        loend = qd[gfield.name+'_lo']
                        hiend = qd[gfield.name+'_hi']
                    hards[gf] = (oper, loend, hiend)
    # also do it for non virtual fields
    msize = tableSize(myModel)
    for fname, frange in desiderata.iteritems():
        if fname not in scales:
            field = resolveField(myModel, fname)
            scales[fname] = scaleEval(myModel, field, frange[0], frange[1], msize, dbFieldRef(field))

    query = query.prefetch_related(*allthroughfields)

    myweight = totalweight(myModel, qdatas)
    rescore = dict()
    for x in query:
        ## not sure why, but this can come back as a Decimal or something odd
        myscore = float(getattr(x, 'score'))
        mysum = myweight * myscore
        maxsum = myweight
        valid = True
        for tf in allthroughfields:
            try:
                instance = getattr(x,tf)
                if instance is not None:
                    gscore = instanceScore(instance, desiderata, scales=scales)
                    for gfs in gargs.values():
                        for gfield in gfs:
                            if tf == gfield.throughfield_name:
                                try:
                                    oper, loend, hiend = hards[gfield]
                                    gv = getattr(instance,gfield.name)
                                    if ((oper == 'IN') and
                                        ((gv < loend) or (gv > hiend))):
                                        valid = False
                                    elif ((oper == 'NOT IN') and
                                          (gv >= loend) and (gv <= hiend)):
                                        valid = False
                                    elif ((oper == '=') and
                                          (gv != loend)):
                                        valid = False
                                    elif ((oper == '!=') and
                                          (gv != loend)):
                                        valid = False
                                except KeyError:
                                    pass
                                try:
                                    gweight = gweights[gfield]
                                    mysum = mysum + gweight * gscore
                                    maxsum = maxsum + gweight
                                except AttributeError:
                                    valid = False
                else:
                    valid = False
            except ObjectDoesNotExist: # dirty data!
                valid = False

        if not valid:
            rescore[x] = 0
        elif mysum == maxsum:
            rescore[x] = 1
        else:
            rescore[x] = mysum / maxsum
    query = [x[0] for x in sorted(rescore.iteritems(), key=itemgetter(1), reverse=True)]
    results = []
    for x in query:
        setattr(x, 'score', rescore[x])
        if rescore[x] >= threshold:
            results.append(x)

    return results


def getMatches(myModel, qdatas, threshold=0.0, orders=[], queryGenerator=None):
    """
    Get the query results
    """
    soft = (threshold < 1.0)
    threshold = threshold - 1E-12 # account for floating point errors
    #results = []
    #print(qdatas)
    #hardfilter = makeFilters(myModel, qdatas, False)
    myfilter = makeFilters(myModel, qdatas, soft)

    if soft:
        scorer = sortFormula(myModel, qdatas)
    else:
        scorer = 1

    if isAbstract(myModel):
        aggresults = []
        scores = dict()
        for subm in concreteDescendants(myModel):
            subresults = getMatches(subm, qdatas,
                                    threshold=threshold,
                                    queryGenerator=queryGenerator)
            for x in subresults:
                scores[x] = x.score
            aggresults = aggresults + [x for x in subresults]
        aggresults = sorted(aggresults,key=lambda x: scores[x])

        return aggresults
    else:
        if queryGenerator is None:
            baseQuery = myModel.objects.all()
        else:
            baseQuery = queryGenerator(myModel)

        gargs = virtualArguments(myModel, qdatas, soft)
        processVirtual = len(gargs.keys()) > 0

        if (soft or processVirtual) and (threshold is None):
            threshold = sortThreshold()

        if myfilter:
            query = baseQuery.filter(myfilter)
        else:
            query = baseQuery
        if (scorer != 1):
            ## this code may not be needed in some versions of Django
            ## apparently count() gets confused when extra refers
            ## to fields inherited from a non-abstract class
            ## it doesn't include those (parent) table
            ## same problem doesn't seem to occur on selection queries
            ## we need to make the connection ourselves
            ## WARNING: This probably will fail on grandparents, etc.
            extramodels = [ ]
            for b in desiredRanges(qdatas).keys():
                try:
                    fmodel = fieldModel(resolveField(myModel, b))
                    if ((fmodel != myModel) and (fmodel not in extramodels)
                        and issubclass(myModel, fmodel)):
                        extramodels.append(fmodel)
                except AttributeError:
                    pass

            extratables = [db_table(m) for m in extramodels]
            extrawhere = [dbFieldRef(parentField(myModel,p))+" = "+dbFieldRef(pk(p)) for p in extramodels if parentField(myModel,p) is not None]
            extrawhere.append('%s >= %s' % (scorer, threshold))
            query = query.extra(tables=extratables, where=extrawhere)
        orders = ['-score'] + orders + [pk(myModel).name]
        query = query.extra(select={'score': scorer}).order_by(*orders)

        ## not retrieving GenericKey fields may just mean we end up
        ## loading them one at a time, later, so don't defer those
        ## This might be too loose (e.g., if the GenericKey is not used
        cantDefer = []
        cantOnly = []
        for x in modelFields(myModel):
            try:
                cantDefer.extend([x.ct_field, x.fk_field])
                cantOnly.append(x.name)
            except AttributeError:
                pass
        # deferFields = [x.name for x in modelFields(myModel) if maskField(x) and isinstance(x, Field) and x.name not in cantDefer]
        ## including stuff like VirtualIncludedFields on reverse relations
        ## blows up, so restrict only to things that have a column
        ## may be overly restrictive
        columnFields = [x.name for x in modelFields(myModel) if hasattr(x, 'column')]
        onlyFields = []
        for x in modelFields(myModel):
            if isinstance(x, Field) and (not maskField(x) or x.name in cantDefer) and (x.name not in cantOnly):
                try:
                    if (x.throughfield_name is not None) and (x.throughfield_name not in cantOnly) and (x.throughfield_name in columnFields):
                        onlyFields.append(x.throughfield_name)
                        # assert(hasattr(x.targetFields()[0], 'column'))
                except AttributeError:
                    if x.name in columnFields:
                        onlyFields.append(x.name)
        ## defer isnt' working right on inherited models in Django 1.5
        ## only does, however
        ##query = query.defer(*deferFields)
        query = query.only(*onlyFields)

        if processVirtual:
            return virtualProcessing(myModel, qdatas, query, gargs, threshold)
        else:
            return query


def retrieve(fullids, flat=True):
    """
    Return a bunch of records specifid by fullid
    """
    groupedIds  = dict()
    for fid in fullids:
        moduleName, modelName, rid = fid.split(':')
        myModel = resolveModel(moduleName, modelName)
        if myModel not in groupedIds:
            groupedIds[myModel] = []
        groupedIds[myModel].append(rid)
    groupedRecords = dict()
    if flat:
        for myModel,ids in groupedIds.iteritems():
            for rec in myModel.objects.filter(pk__in=ids):
                groupedRecords[fullid(rec)] = rec
        ## return in original order
        return [groupedRecords[fid] for fid in fullids]
    else:
        return [myModel.objects.filter(pk__in=ids) for myModel,ids in groupedIds.iteritems()]


def unitScore(value, lorange, hirange, median):
    """
    Scores a value from 1 (best) to 0 (worst)
    """
    if (lorange != 'min') and (value < lorange):
        if value is None:
            return 0
        absdiff = lorange - value
    elif (hirange != 'max') and (value > hirange):
        if value is None:
            return 0
        absdiff = value - hirange
    else:
        absdiff = 0

    if (median is None) or (absdiff == 0):
        return 1
    else:
        if isinstance(median, datetime.timedelta):
            median = median.total_seconds()
        if isinstance(absdiff, datetime.timedelta):
            absdiff = absdiff.total_seconds()
        return median / (median + absdiff)


def multiScore(model, values, desiderata, scales=None):
    """
    Scores an instance in python, not mysql
    """
    if scales is None:
        scales = {}
    score = 0
    count = 0
    for d in desiderata.keys():
        b = resolveField(model, d)
        if (d in scales):
            scale = scales[d]
        else:
            print("BAD")
            print(d)
            print(scales)
            raise Exception("This is bad news!")
        score = score + unitScore(values[d], desiderata[d][0], desiderata[d][1], scale)
        count = count + 1

    if (count == 0):
        return 1
    else:
        return score / count


def instanceScore(instance, desiderata, scales=None):
    """
    Scores an instance in python, not mysql
    """
    if scales is None:
        scales = {}
    values = {}
    newdesiderata = {}
    for d in desiderata.keys():
        try:
            values[d] = getattr(instance, d)
            newdesiderata[d] = desiderata[d]
        except AttributeError:
            pass # no such attribute- should clean this up elsewhere
    return multiScore(instance.__class__, values, newdesiderata, scales=scales)


## The following is experimental and not currently in use

def makeQinfo(model, query, fld, loend, hiend, order=None):
    """
    Helper function for sortedTopK; may go away
    """
    if loend is not None:
        query = query.filter(**{fld + '__gte': loend})
    if hiend is not None:
        query = query.filter(**{fld + '__lt': hiend})

    return {'query': query, 'order': order}


def sortedTopK(model, qdatas, query, k):
    """
    Threshold algorithm, still being optimized
    """
    desiderata = desiredRanges(qdatas)
    return sortedTopKRanges(model, desiderata, query, k)


def sortedTopKRanges(model, desiderata, query, k):
    """
    Threshold algorithm, still being optimized
    """
    print("Oooh")
    print(query.query)
    #pageSize = 10000 ## should be independent of the problem, although if table size isn't much larger, should approach differently
    print(desiderata)
    if len(desiderata) == 0:
        ## any k are top k
        return query[:k]
    #pageSize = max(pageSize, int(k/len(desiderata)))

    times = 10

    runtime = datetime.datetime.now(pytz.utc)
    tsize = tableSize(model)
##    runtime = timer(runtime, "Table size")
    scorer = sortFormulaRanges(model, desiderata)  # SLOW!!
    #query = query.extra(select={'score': scorer}, order_by=['-score'])
    #print(query.query)
##    runtime = timer(runtime,"Sort formula")

    if (tsize <= k):
        ## format is a little awkward in this case, but consistent with the tsize > k case
        keep = sorted(query, key=lambda x: instanceScore(x, desiderata, scales=scales), reverse=True)
        results = keep[0:k]
#        results = {}
#        for x in keep[0:k]:
#            results[x[model._meta.pk.attname]] = x
    else:
        results = {}
        qinfo = {}
#        qbackup = {}  # additional queries if the primary runs out
#        qscorer = {}  # function to score individual elements; will need more work to be general beyond current fn
        threshold = {}  # how deep into each criteria we are

        scales = {}
        #vfields = desiderata.keys()
        #vfields.append(model._meta.pk.attname)
        #vfields.append('score')
        #vquery = query.extra(select={'score': scorer}).values(*vfields)
        vquery = query

        for fld in desiderata:
            loend = desiderata[fld][0]
            if (loend is 'min'):
                loend = None
            hiend = desiderata[fld][1]
            if (hiend is 'max'):
                hiend = None

            newtime = datetime.datetime.now(pytz.utc)
##            scales[fld] = medianEval(model, baseScore(dbFieldRef( resolveField(model, fld) ),loend, hiend), tsize)
            scales[fld] = scaleEval(model, resolveField(model, fld), loend, hiend, tsize, dbFieldRef(resolveField(model, fld)))
            newtime = timer(newtime, " << inner scale >>")
            window = segmentBounds(model, fld, loend, hiend)
            print(loend, hiend, window)
            if window[0] is None:
                mid = window[1]
            elif window[1] is None:
                mid = window[0]
            else:
                mid = (window[0] + window[1]) * 0.5  # arbitrary split, really 1st time could get away with 1 query
            qinfo[fld] = [makeQinfo(model, vquery, fld, window[0], mid, 'desc'),
                          makeQinfo(model, vquery, fld, mid, window[1], 'asc')]

        wanting = True
        runtime = timer(runtime, "Setup")

        while (wanting):
            for fld in desiderata:
##                excluders = {}
                for qpack in qinfo[fld]:
                    q = qpack['query']
                    # if (times == 10):
                        # maybe this doesn't do anything
                        # runtime = timer(runtime, q.count())
                    minlist = q[0:k]
                    if len(minlist) > 0:
                        minScore = str(instanceScore(list(q[0:k])[-1], desiderata, scales=scales))
                    else:
                        minScore = '0'  # doesn't matter, there are no matches
                    runtime = timer(runtime, 'minScore = ' + minScore)
                    #q=q.extra(select={'score': scorer}, order_by=['-score'])
                    runtime = timer(runtime, q.extra(select={'score': scorer}, where=[scorer + ' >= ' + minScore]).count())
                    q = q.extra(select={'score': scorer}, where=[scorer + ' >= ' + minScore], order_by=['-score'])
                    #q = q.extra(select={'score': scorer})
                    runtime = timer(runtime, str(q.query))
                    q = q[0:k]
                    qresults = list(q)
                    runtime = timer(runtime, "I got " + str(len(qresults)) + " back")

                    ## could do something fancy about not returning stuff below kth score,
                    ## but might also be better done in db
                    for x in qresults:
                        # results[x[model._meta.pk.attname]] = x
                        results[getattr(x, pk(model).attname)] = x

                runtime = timer(runtime, fld + " A")

                ## update thresholds
                if (window[0] is None) and (window[1] is None):
                    threshold[fld] = None
                    del threshold[fld]
                elif (window[0] is None):
                    threshold[fld] = window[1]
                elif (window[1] is None):
                    threshold[fld] = window[0]
                else:
                    ## this assumes to much about scoring fn, and that loend, hiend != None
                    if (loend - window[0]) < (window[1] - hiend):
                        threshold[fld] = window[0]
                    else:
                        threshold[fld] = window[1]

                ## update queries
                newqs = []
                for qpack in qinfo[fld]:
                    if (qpack['order'] == 'desc'):
                        if (window[0] is not None):
                            hibound = window[0]
                            window[0] = nextPercentile(model, fld, window[0], 'lt')
                            newqs.append(makeQinfo(model, vquery, fld, window[0], hibound, qpack['order']))
                    else:
                        if (window[1] is not None):
                            lobound = window[1]
                            window[1] = nextPercentile(model, fld, window[1], 'gt')
                            newqs.append(makeQinfo(model, vquery, fld, lobound, window[1], qpack['order']))
                qinfo[fld] = newqs

                runtime = timer(runtime, fld + " D")

            ## sort and set to top k; not efficient as could be
            # keep = sorted(results.values(), key=lambda x: multiScore(model, x, desiderata, scales = scales), reverse=True)[0:k]
            keep = sorted(results.values(), key=lambda x: instanceScore(x, desiderata, scales=scales), reverse=True)[0:k]
            results = {}
            for x in keep:
                # results[x[model._meta.pk.attname]] = x
                results[getattr(x, pk(model).attname)] = x

#            check = wanting
            for fld in desiderata:
                if fld not in threshold:
                    wanting = False

            ## set wanting to false if synthetic instance evals to >= kth result

            times = times - 1
            if times == 0:
                wanting = False
                print("\n\n\n\nI am bailing!!!\n\n\n\n")
            if wanting and len(keep) > 0:
                scoreA = multiScore(model, threshold, desiderata, scales=scales)
                # scoreB = multiScore(model, keep[-1], desiderata, scales = scales)
                scoreB = instanceScore(keep[-1], desiderata, scales=scales)
                print(scoreA, scoreB)
                print 'Thresh', threshold, scoreA
                print 'Last', keep[-1], scoreB
                if (scoreA <= scoreB) and (len(results) >= k):
                    # Threshold exceeded!
                    wanting = False
            runtime = timer(runtime, " endcheck")
        runtime = timer(runtime, results.keys())
        # results = model.objects.filter(pk__in=results.keys())
        results = results.values()
        runtime = timer(runtime, results)
        results = sorted(results, key=lambda x: instanceScore(x, desiderata, scales=scales), reverse=True)
    print("Aaah")
    return results
