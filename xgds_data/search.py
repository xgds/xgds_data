# __BEGIN_LICENSE__
# Copyright (C) 2008-2014 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import re
import time
import datetime

from math import floor, log10, pow as mpow  # shadows built-in pow()
from operator import itemgetter

from django import forms
from django.db import connection
from django.db.models import Q
from django.db.models.fields import PositiveIntegerField, PositiveSmallIntegerField
from django.db.models.fields.related import OneToOneField, ManyToManyField, RelatedField

from xgds_data.introspection import modelFields, resolveField, maskField, isAbstract, concreteDescendents, pk
from xgds_data.models import cacheStatistics
if cacheStatistics():
    from xgds_data.models import ModelStatistic
from xgds_data.DataStatistics import tableSize, segmentBounds, nextPercentile


def timer(t, msg):
    newtime = datetime.datetime.now()
    print([str(newtime - t), str(msg)])
    return newtime


def divineWhereClause(myModel, filters):
    """
    Pulls out the where clause and quotes the likely literals. Probably really brittle and should be replaced
    """
    post = str(myModel.objects.filter(filters).query)
    orderbystart = post.find(' ORDER BY ')
    if orderbystart > -1:
        post = post[:orderbystart]
    wherestart = post.find(' WHERE ')
    if wherestart > -1:
        newwhere = ' WHERE '
        for seg in re.compile("( [AO][NR]D? )").split(post[(wherestart + 7):]):
            eqpos = seg.find('= ')
            if (eqpos > -1):
                quotable = seg.rstrip(') ')[(eqpos + 1):].strip()
                quotepos = seg.find(quotable)
                newseg = (seg[:quotepos] +
                          '"' + quotable + '"' +
                          seg[(quotepos + len(quotable)):])
            else:
                newseg = seg
            newwhere = newwhere + newseg
    else:
        newwhere = None

    return newwhere


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


def makeFilters(formset, soft=True):
    """
    Helper for searchChosenModel; figures out restrictions given a formset
    """
    filters = None
    ##if (threshold == 1):
    ##    filters = None
    ##else:
    ##    filters = Q(**{ 'score__gte' : threshold } )
    ## forms are interpreted as internally conjunctive, externally disjunctive
    for form in formset:
        subfilter = Q()
        for field in form.cleaned_data:
            if form.cleaned_data[field] is not None:
                clause = None
                negate = False
                if field.endswith('_operator'):
                    pass
                elif (field.endswith('_lo') or field.endswith('_hi')):
                    base = field[:-3]
                    loval = form.cleaned_data[base + '_lo']
                    hival = form.cleaned_data[base + '_hi']
                    operator = form.cleaned_data[base + '_operator']
                    if soft and (operator == 'IN~'):
                        ## this isn't a restriction, so ignore
                        pass
                    else:
                        negate = form.cleaned_data[base + '_operator'] == 'NOT IN'
                        if (loval is not None and hival is not None):
                            if loval > hival:
                                ## hi and lo are reversed, assume that is a mistake
                                swap = loval
                                loval = hival
                                hival = swap
                            if field.endswith('_lo'):
                                ## range query- handle on _lo to prevent from doing it twice
                                ## this aren't simple Q objects so don't set clause variable
                                if negate:
                                    negate = False
                                    subfilter &= (Q(**{base + '__lt': loval}) |
                                                  Q(**{base + '__gt': hival}))
                                else:
                                    subfilter &= (Q(**{base + '__gte': loval}) &
                                                  Q(**{base + '__lte': hival}))
                        elif loval is not None:
                            clause = Q(**{base + '__gte': loval})
                        elif hival is not None:
                            clause = Q(**{base + '__lte': hival})
                elif isinstance(form[field].field, forms.ModelMultipleChoiceField):
                    clause = Q(**{field + '__in': form.cleaned_data[field]})
                    negate = form.cleaned_data[field + '_operator'] == 'NOT IN'
                elif isinstance(form[field].field, forms.ModelChoiceField):
                    negate = form.cleaned_data[field + '_operator'] == '!='
                    clause = Q(**{field + '__exact': form.cleaned_data[field]})
                elif isinstance(form[field].field, forms.ChoiceField):
                    negate = form.cleaned_data[field + '_operator'] == '!='
                    if form.cleaned_data[field] == 'True':
                        ## True values appear to be represented as numbers greater than 0
                        clause = Q(**{field + '__gt': 0})
                    elif form.cleaned_data[field] == 'False':
                        ## False values appear to be represented as 0
                        clause = Q(**{field + '__exact': 0})
                else:
                    operator = form.cleaned_data[field + '_operator']
                    if form.cleaned_data[field] is None or re.match("\s*$",form.cleaned_data[field]):
                        pass
                    else:
                        if (operator == '=~'):
                            pass
                        else:
                            negate = (operator == '!=')
                            clause = Q(**{field + '__icontains': form.cleaned_data[field]})
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


def scoreNumericOLD(fieldName, val, minimum, maximum):
    """
    provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
    """
    if val is None:
        return '1'  # same constant for everyone, so it factors out
    elif val == 'min':
        val = minimum
    elif val == 'max':
        val = maximum
    if isinstance(val, list):
        lorange = val[0]
        hirange = val[1]
    else:
        lorange = val
        hirange = val

    def mktimeIfNeeded(d):
        if isinstance(d, datetime.datetime):
            return time.mktime(d.timetuple())
        else:
            return d

    lorange = mktimeIfNeeded(lorange)
    hirange = mktimeIfNeeded(hirange)
    minimum = mktimeIfNeeded(minimum)
    maximum = mktimeIfNeeded(maximum)

    if ((lorange <= minimum) and (maximum <= hirange)):
        return '1'
    else:
        return ("1-(greatest(least({1}-{0},{0}-{2}),0)/{3})"
                .format(fieldName,
                        lorange,
                        hirange,
                        max(0, lorange - minimum, maximum - hirange)))


def baseScore(fieldRef, lorange, hirange):
    """
    provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
    """
    timeConversion = False
    if isinstance(lorange, datetime.datetime):
        timeConversion = True
        lorange = time.mktime(lorange.timetuple())
    if isinstance(hirange, datetime.datetime):
        timeConversion = True
        hirange = time.mktime(hirange.timetuple())
    ## perhaps could swap lo, hi if lo > hi
    if (timeConversion):
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
    table = model._meta.db_table
    pkname = pk(model).attname
    randselect = 'SELECT {1} from {0} WHERE {2} IS NOT NULL ORDER BY RAND() limit {3}'.format(table, pkname, expression, size)
    ## turns out mysql has a direct way of selecting random ways; below is a more complicated way that requires
    ## consecutive ids, etc
    #randselect = '(SELECT CEIL(RAND() * (SELECT MAX({1}) FROM {0})) AS {1} from {0} limit {2})'.format(table, pkname, size)
    if offset is None or limit is None:
        sql = ('select {2} as score from {0} JOIN ({3}) AS r2 USING ({1}) order by score;'
               .format(table, pkname, expression, randselect))
    else:
        sql = ('select {2} as score from {0} JOIN ({3}) AS r2 USING ({1}) order by score limit {4},{5};'
               .format(table, pkname, expression, randselect, offset, limit))
    cursor = connection.cursor()
##    runtime = datetime.datetime.now()
    cursor.execute(sql)
##    runtime = timer(runtime, "<<< inner random sample >>>")
    return cursor.fetchall()


def joinClause(parentLinkField):
    """
    Figures out the additional clause needed for linkages to a parent class
    """
    return '{0}.{1} = {2}.{3}'.format(parentLinkField.model._meta.db_table,
                                      pk(parentLinkField.model).attname,
                                      parentLinkField.rel.get_related_field().model._meta.db_table,
                                      pk(parentLinkField.rel.get_related_field().model).attname)


def countMatches(model, expression, where, threshold):
    """
    Get the full count of records matching the restriction; can be slow
    """
    joinFields = [x for x in modelFields(model) if isinstance(x, OneToOneField) and x.rel.parent_link]
    joinClauses = [joinClause(plf) for plf in joinFields]
    if joinClauses:
        whereClauses = joinClauses
        if where:
            whereClauses.insert(0, where)
            where = ' AND '.join(whereClauses)
        else:
            where = ' AND '.join(whereClauses)
            where = "WHERE " + where

    tables = [model._meta.db_table]
    for f in joinFields:
        tables.append(f.rel.get_related_field().model._meta.db_table)
    cursor = connection.cursor()
    if where:
        sql = 'select sum({1} >= {3}) from {0} {2};'.format(','.join(tables), expression, where, threshold)
    else:
        sql = 'select sum({1} >= {2}) from {0};'.format(','.join(tables), expression, threshold)
##    runtime = datetime.datetime.now()
    cursor.execute(sql)
##    runtime = timer(runtime, "<<< inner count matches >>>")
    return int(cursor.fetchone()[0])


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
        while (len(result) == 0) and (triesLeft > 0):
            ## not sure why, but sometimes nothing is returned
            result = randomSample(model, expression, sampleSize, sampleSize / 2, 1)
            triesLeft = triesLeft - 1
        if len(result) == 0:
            return None
        else:
            return result[0][0]


def medianRangeEval(model, field, lorange, hirange, size, fieldRef):
    """
    Quick mysql-y way of estimating the median from a range sample
    """
    if cacheStatistics():
        ## I'm sure there's a great reason why \d is not working like [0-9] for me, but I don't understand it
        ## So, clunky looking regex
        percentiles = ModelStatistic.objects.filter(model=model.__name__).filter(field=field.name).filter(statistic__regex=r'p[0-9]+$')
        if (percentiles.count() > 0):
            if lorange == hirange:
                vals = sorted([abs(x.value - lorange) for x in percentiles])
            elif lorange is None or lorange == 'min':
                vals = sorted([max(0, x.value - hirange) for x in percentiles])
            elif hirange is None or hirange == 'max':
                vals = sorted([max(0, lorange - x.value) for x in percentiles])
            else:
                vals = sorted([max(0, lorange - x.value, x.value - hirange) for x in percentiles])
            ##print('Guessed')
            return(vals[int(round(len(vals) * 0.5)) - 1])
    ## if we haven't returned a value already
    ##print('NOT Guessed')
    return medianEval(model, baseScore(fieldRef, lorange, hirange), size)


def dbFieldRef(field):
    """
    return the alias for this field in the database query
    """
    return field.model._meta.db_table + '.' + field.attname


def autoweight(model, field, lorange, hirange, tableSize):
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
    # median = medianRangeEval(field.model, field, lorange, hirange, tableSize, fieldRef)
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
    median = medianRangeEval(field.model, field, lorange, hirange, tsize, fieldRef)
    if median is None:
        return '1'
    elif median == 0:
        ## would get divide by zero with standard formula below
        ## defining 0/x == 0 always, limit of standard formula leads to special case for 0, below.
        return "({0} = {1})".format(baseScore(fieldRef, lorange, hirange), median)
    else:
        return "1 /(1 + {0}/{1})".format(baseScore(fieldRef, lorange, hirange), median)
    #return "1-(1 + {1}) /(2 + 2 * {0})".format(baseScore(fieldRef, lorange, hirange),
    #                    medianEval(model._meta.db_table, baseScore(fieldRef, lorange, hirange), tsize))


def desiredRanges(frms):
    """
    Pulls out the approximate (soft) constraints from the form
    """
    desiderata = dict()
    ## frms are interpreted as internally conjunctive, externally disjunctive
    for form in frms:
        for field in form.cleaned_data:
            if (form.cleaned_data[field] is not None) and (field.endswith('_operator')):
                base = field[:-9]
                operator = form.cleaned_data[field]
                if operator == 'IN~':
                    loval = form.cleaned_data[base + '_lo']
                    hival = form.cleaned_data[base + '_hi']
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
                    print('what is ',operator)
                else:
                    None
    return desiderata


def sortFormula(model, formset):
    """
    Helper for searchChosenModel; comes up with a formula for ordering the results
    """
    return sortFormulaRanges(model, desiredRanges(formset))


def sortFormulaRanges(model, desiderata):
    """
    Helper for searchChosenModel; comes up with a formula for ordering the results
    """
    if (len(desiderata) > 0):
        tsize = tableSize(model)
#        weights = dict([(b,autoweight(model, resolveField(model, b), desiderata[b][0], desiderata[b][1], tsize)) \
#                              for b in desiderata.keys()])
        totalweight = len(desiderata)
#        for w in weights.values():
#            totalweight = totalweight + w
        scores = dict([(b,scoreNumeric(model, resolveField(model, b), desiderata[b][0], desiderata[b][1], tsize)) \
                              for b in desiderata.keys()])
        formula = ' + '.join([scores[b] for b in desiderata.keys()])
        return '({0})/{1} '.format(formula, totalweight)  # scale to have a max of 1
    else:
        return None


def unitScore(value, lorange, hirange, median):
    """
    Scores a value from 1 (best) to 0 (worst)
    """
    if (lorange != 'min') and (value < lorange):
        absdiff = lorange - value
    elif (hirange != 'max') and (value > hirange):
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


def multiScore(model, values, desiderata, medians=None):
    """
    Scores an instance in python, not mysql
    """
    if medians is None:
        medians = {}
    score = 0
    count = 0
    tsize = None
    for d in desiderata.keys():
        b = resolveField(model, d)
        ## Yuk ... need to convert if field is unsigned
        unsigned = False
        if isinstance(b, (PositiveIntegerField, PositiveSmallIntegerField)):
            unsigned = True
        ## Add table designation to properly resolve a field name that has another SQL interpretation
        ## (for instance, a field name 'long')
        fieldRef = dbFieldRef(b)
        if (unsigned):
            fieldRef = "cast({0} as SIGNED)".format(fieldRef)

        if (d in medians):
            median = medians[d]
        else:
            print("BAD")
            raise Exception("This is bad news!")
            if not tsize:
                tsize = tableSize(model)
            median = medianEval(b.model, baseScore(fieldRef,desiderata[d][0], desiderata[d][1]), tsize)
        score = score + unitScore(values[d], desiderata[d][0], desiderata[d][1], median)
        count = count + 1

    if (count == 0):
        return 1
    else:
        return score / count


def instanceScore(instance, desiderata, medians=None):
    """
    Scores an instance in python, not mysql
    """
    if medians is None:
        medians = {}
    values = {}
    for d in desiderata.keys():
        values[d] = getattr(instance, d)
    return multiScore(instance.__class__, values, desiderata, medians=medians)


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
    return ((page - 1)* pageSize, page * pageSize)


def getResults(myModel, softFilter, scorer = None, queryStart = 0, queryEnd = None, minCount = None):
    """
    Get the query results as dicts, so relevance scores can be included
    """
    results = []
    if isAbstract(myModel):
        aggresults = []
        aggcount = 0
        for subm in concreteDescendents(myModel):
            subresults, subcount = getResults(subm, softFilter, scorer = scorer, queryStart = 0, queryEnd = queryEnd, minCount = minCount)
            aggcount = aggcount + subcount
            aggresults = aggresults + subresults
        aggresults = sorted(aggresults,key=itemgetter('score'), reverse=True)
        aggresults = aggresults[queryStart:]
        return (aggresults, aggcount)
    else:
        query = myModel.objects.filter(softFilter)
        queryFields = [x.name for x in modelFields(myModel) if not maskField(myModel,x) ]
        if scorer:
            query = query.extra(select={'score': scorer}, order_by=['-score'])
            ## totalCount = countApproxMatches(myModel, scorer, query.count(), sortThreshold())
            totalCount = countMatches(myModel,
                                       scorer,
                                       divineWhereClause(myModel, softFilter),
                                       sortThreshold())
            if (minCount is not None) and (totalCount < minCount):
                ## this only makes sense if it's an approximate count
                ## and that approximate count is too low
                totalCount = minCount
        else:
            query = query.extra(select={'score': 1})
            # hardCount = query.count()
            if minCount is None:
                totalCount = query.values(*queryFields).count()
            else:
                totalCount = minCount
    
        queryFields.append('score')
        qvalues = query.values(*queryFields)
    
        if queryEnd:
            queryEnd = min(totalCount,queryEnd)
        else:
            queryEnd = totalCount
            
        qvalues = qvalues[queryStart:queryEnd]
    
        foreigners = dict([ (f, set()) for f in modelFields(myModel) if isinstance(f,RelatedField)])
        for d in qvalues:
            for k in iter(foreigners):
                try:
                    relatives = d[k.name]
                except KeyError:
                    pass  # it's ok if that key is missing
                else:
                    try:
                        iterator = iter(relatives)
                        assert not isinstance(relatives, basestring)
                    except (TypeError, AssertionError):
                        # not iterable
                        foreigners[k].add(relatives)
                    else:
                        for f in iterator:
                            foreigners[k].add(f)
                
        for f in iter(foreigners):
            relf = f.rel.get_related_field()
            objects = relf.model.objects.filter(**{relf.attname + '__in': foreigners[f]})
            foreigners[f] = dict([(getattr(x,relf.name),x) for x in objects])
            
        for d in qvalues:
            resultd = d.copy()
            resultd['__class__'] = myModel
            for f in iter(foreigners):
                if f.name in resultd:
                    try:
                        resultd[f.name] = foreigners[f][resultd[f.name] ]
                    except KeyError:
                        del resultd[f.name] # presumably this means something is not consistent in the model, it does happen
    
            modeld = dict( [ (f.name,resultd[f.name]) \
                                 for f in modelFields(myModel) \
                                 if f.name in resultd \
                                 ## yuk... but something goes wrong insert M2MF
                                 and not isinstance(f,ManyToManyField) ] )
            instance = myModel(**modeld)
            resultd['__instance__'] = instance
            resultd['__string__'] = str(instance)
            results.append( resultd )
        return (results, totalCount)


def makeQinfo(model, query, fld, loend, hiend, order=None):
    """
    Helper function for sortedTopK; may go away
    """
    if loend is not None:
        query = query.filter(**{fld + '__gte': loend})
    if hiend is not None:
        query = query.filter(**{fld + '__lt': hiend})

    return {'query': query, 'order': order}


def sortedTopK(model, formset, query, k):
    """
    Threshold algorithm, still being optimized
    """
    desiderata = desiredRanges(formset)
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

    runtime = datetime.datetime.now()
    tsize = tableSize(model)
##    runtime = timer(runtime, "Table size")
    scorer = sortFormulaRanges(model, desiderata)  # SLOW!!
    #query = query.extra(select={'score': scorer}, order_by=['-score'])
    #print(query.query)
##    runtime = timer(runtime,"Sort formula")

    if (tsize <= k):
        ## format is a little awkward in this case, but consistent with the tsize > k case
        keep = sorted(query, key=lambda x: instanceScore(x, desiderata, medians=medians), reverse=True)
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

        medians = {}
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

            newtime = datetime.datetime.now()
##            medians[fld] = medianEval(model, baseScore(dbFieldRef( resolveField(model, fld) ),loend, hiend), tsize)
            medians[fld] = medianRangeEval(model, resolveField(model, fld), loend, hiend, tsize, dbFieldRef(resolveField(model, fld)))
            newtime = timer(newtime, " << inner median >>")
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
                        minScore = str(instanceScore(list(q[0:k])[-1], desiderata, medians=medians))
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
            # keep = sorted(results.values(), key=lambda x: multiScore(model, x, desiderata, medians = medians), reverse=True)[0:k]
            keep = sorted(results.values(), key=lambda x: instanceScore(x, desiderata, medians=medians), reverse=True)[0:k]
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
                scoreA = multiScore(model, threshold, desiderata, medians=medians)
                # scoreB = multiScore(model, keep[-1], desiderata, medians = medians)
                scoreB = instanceScore(keep[-1], desiderata, medians=medians)
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
        results = sorted(results, key=lambda x: instanceScore(x, desiderata, medians=medians), reverse=True)
    print("Aaah")
    return results
