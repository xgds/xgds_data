# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from datetime import datetime

from django.db import models
from django.contrib.auth.models import User
from django.http import HttpRequest

from xgds_data import settings
from xgds_data.logconfig import logEnabled


def cacheStatistics():
    return (hasattr(settings, 'XGDS_DATA_CACHE_STATISTICS') and
            settings.XGDS_DATA_CACHE_STATISTICS)


def truncate(val, limit):
    """
        shortens the value if need be so that it does not exceed db limit
        """
    if val is None:
        return None
    else:
        return val[0:(limit - 2)]  # save an extra space because the db seems to want that


class VirtualField(models.Field):
    description = "A hand of cards (bridge style)"

    def __init__(self, throughfield, base_name, base_verbose_name, *args, **kwargs):
        super(VirtualField, self).__init__(*args, **kwargs)
        #self.model = basefield.model
        self.throughfield = throughfield
        self.name = base_name
        self.verbose_name = base_verbose_name



## taken from http://stackoverflow.com/questions/4581789/how-do-i-get-user-ip-address-in-django
def get_client_ip(request):
    """
        Attempt to extract ip address from request object
        """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


if logEnabled():
    class RequestLog(models.Model):
        timestampSeconds = models.DateTimeField(blank=False)
        path = models.CharField(max_length=256, blank=False)
        ipaddress = models.CharField(max_length=256, blank=False)
        #user = models.CharField(max_length=64, blank=False)  # probably can be a foreign key
        user = models.ForeignKey(User, null=True, blank=True)
        session = models.CharField(max_length=64, null=True, blank=True)
        referer = models.CharField(max_length=256, null=True, blank=True)
        user_agent = models.CharField(max_length=256, null=True, blank=True)

        @classmethod
        def create(cls, request):
            ref = request.META.get('HTTP_REFERER', None)
            uagent = request.META.get('HTTP_USER_AGENT', None)
            uzer = request.user
            if uzer.id is None:
                uzer = None

            # rlog = cls(path=request.path,ipaddress=get_client_ip(request),user=request.user.__str__())
            rlog = cls(timestampSeconds=datetime.utcnow(),
                       path=truncate(request.path, 256),
                       ipaddress=truncate(get_client_ip(request), 256),
                       user=uzer,
                       session=truncate(request.session.session_key, 64),
                       referer=truncate(ref, 256),
                       user_agent=truncate(uagent, 256))
            return rlog

        def __unicode__(self):
            return 'Request %s:%s' % (self.id, self.path)


    class RequestArgument(models.Model):
        request = models.ForeignKey(RequestLog, null=False, blank=False)
        name = models.CharField(max_length=256, blank=False)
        value = models.TextField(blank=True)


    class ResponseLog(models.Model):
        timestampSeconds = models.DateTimeField(blank=False)
        request = models.ForeignKey(RequestLog, null=False, blank=False)
        template = models.CharField(max_length=256, blank=True)
        
        @classmethod
        def create(cls,request,template=None):
            return cls(timestampSeconds=datetime.utcnow(),request=request,template=template)


    class ResponseArgument(models.Model):
        response = models.ForeignKey(ResponseLog, null=False, blank=False)
        name = models.CharField(max_length=256, blank=False)
        value = models.CharField(max_length=1024, blank=True)

    class ResponseList(models.Model):
        response = models.ForeignKey(ResponseLog, null=False, blank=False)
        rank = models.PositiveIntegerField(blank=False)
        fclass = models.CharField(max_length=1024, blank=True)
        fid = models.PositiveIntegerField(blank=False)  # might be risky to assume this is always a pos int


    class HttpRequestReplay(HttpRequest):
        def __init__(self, request, path, data, *args, **kwargs):
            HttpRequest.__init__(self, *args, **kwargs)
            self.GET = data
            self.POST = data
            self.REQUEST = data
            self.COOKIES = request.COOKIES
            self.META = request.META
            self.path = path
            self.user = request.user
            self.session = request.session



if cacheStatistics():
    class ModelStatistic(models.Model):
        recorded = models.DateTimeField(blank=False, default=datetime.utcnow())
        model = models.CharField(max_length=256, db_index=True, blank=False)
        field = models.CharField(max_length=256, db_index=True, blank=False)
        statistic = models.CharField(max_length=256, db_index=True, blank=False)
        value = models.FloatField(blank=False)
