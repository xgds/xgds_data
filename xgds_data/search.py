# __BEGIN_LICENSE__
# Copyright (C) 2008-2013 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import re
import time
import datetime

from math import floor, log10, pow as mpow  # shadows built-in pow()

from django import forms
from django.db import connection
from django.db.models import Q
from django.db.models.fields import PositiveIntegerField, PositiveSmallIntegerField

from xgds_data.introspection import modelFields

def divineWhereClause(myModel, filters, formset):
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
                    if ((operator == 'IN~') and soft):
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
                    if form.cleaned_data[field]:
                        negate = form.cleaned_data[field + '_operator'] == '!='
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
        
def scoreNumericOLD(field, val, minimum, maximum):
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
                .format(field,
                        lorange,
                        hirange,
                        max(0, lorange - minimum, maximum - hirange)))

def baseScore(field, lorange, hirange):
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
        field = 'UNIX_TIMESTAMP({0})'.format(field)
    
    if lorange == hirange:
        return "abs({0}-{1})".format(field, lorange)
    elif lorange == 'min':
        return "greatest(0,{0}-{1})".format(field, hirange)
    elif hirange == 'max':
        return "greatest(0,{1}-{0})".format(field, lorange)
    else:
        ##return "greatest(0,least({1}-{0},{0}-{2}))".format(field, lorange, hirange)
        return "greatest(0,{1}-{0},{0}-{2})".format(field, lorange, hirange)

def randomSample(model, expression, size, offset=None, limit=None):
    """
    Selects a random set of records, assuming even distibution of ids; not very Django-y
    """
    table = model._meta.db_table
    pkname = model._meta.pk.attname
    randselect = 'SELECT {1} from {0} WHERE {2} IS NOT NULL ORDER BY RAND() limit {3}'.format(table, pkname, expression, size)
    ## turns out mysql has a direct way of selecting random ways; below is a more complicated way that requires
    ## consecutive ids, etc
    #randselect = '(SELECT CEIL(RAND() * (SELECT MAX({1}) FROM {0})) AS {1} from {0} limit {2})'.format(table, pkname, size)
    if (offset == None) or (limit == None):
        sql = ('select {2} as score from {0} JOIN ({3}) AS r2 USING ({1}) order by score;'
               .format(table, pkname, expression, randselect))
    else:
        sql = ('select {2} as score from {0} JOIN ({3}) AS r2 USING ({1}) order by score limit {4},{5};'
               .format(table, pkname, expression, randselect, offset, limit))
    cursor = connection.cursor()
    cursor.execute(sql)
    return cursor.fetchall()

def countMatches(table, expression, where, threshold):
    """
    Get the full count of records matching the restriction; can be slow
    """
    cursor = connection.cursor()
    if where:
        sql = 'select sum({1} >= {3}) from {0} {2};'.format(table, expression, where, threshold)
    else:
        sql = 'select sum({1} >= {2}) from {0};'.format(table, expression, threshold)
    cursor.execute(sql)
    return cursor.fetchone()[0]

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
    if model.objects.count() == 0:
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

def scoreNumeric(model, field, lorange, hirange, tableSize):
    """
    provide a score for a numeric clause that ranges from 1 (best) to 0 (worst)
    """
    ## Yuk ... need to convert if field is unsigned
    unsigned = False
    for f in modelFields(model):
        if ((f.attname == field) and
            isinstance(f, (PositiveIntegerField, PositiveSmallIntegerField))):
            unsigned = True
    ## Add table designation to properly resolve a field name that has another SQL interpretation
    ## (for instance, a field name 'long')
    field = model._meta.db_table + '.' + field
    if (unsigned):
        field = "cast({0} as SIGNED)".format(field)
    median = medianEval(model, baseScore(field, lorange, hirange), tableSize)
    if median is None:
        return '1'
    elif median == 0:
        ## would get divide by zero with standard formula below
        ## defining 0/x == 0 always, limit of standard formula leads to special case for 0, below.
        return "({0} = {1})".format(baseScore(field, lorange, hirange), median)
    else:
        return "1 /(1 + {0}/{1})".format(baseScore(field, lorange, hirange), median)
    #return "1-(1 + {1}) /(2 + 2 * {0})".format(baseScore(field, lorange, hirange),
    #                    medianEval(model._meta.db_table, baseScore(field, lorange, hirange), tableSize))

def desiredRanges(frms):
    """
    Pulls out the approximate (soft) constraints from the form
    """
    desiderata = dict()
    ## frms are interpreted as internally conjunctive, externally disjunctive
    for form in frms:
        for field in form.cleaned_data:
            if form.cleaned_data[field] is None:
                continue
            if not (field.endswith('_operator') and (form.cleaned_data[field] == 'IN~')):
                continue
            base = field[:-9]
            operator = form.cleaned_data[base + '_operator']
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
    return desiderata

def sortFormula(model, formset):
    """
    Helper for searchChosenModel; comes up with a formula for ordering the results
    """
    desiderata = desiredRanges(formset)
    if (len(desiderata) > 0):
        tableSize = model.objects.count()
        formula = ' + '.join([scoreNumeric(model, b, desiderata[b][0], desiderata[b][1], tableSize) for b in desiderata.keys()])
        return '({0})/{1} '.format(formula, len(desiderata))  # scale to have a max of 1
    else:
        return None

def sortThreshold():
    """
    Guess on a good threshold to cutoff the search results
    """
    ## rather arbitrary cutoff, which would return 30% of results if scores are uniform
    return 0.7