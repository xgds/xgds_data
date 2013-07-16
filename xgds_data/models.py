# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import sys

from django.db import models
from datetime import datetime
from xgds_data import settings


def getModelByName(name):
    appName, modelName = name.split('.', 1)
    modelsName = appName + '.models'
    __import__(modelsName)
    modelsModule = sys.modules[modelsName]
    print modelsModule
    print dir(modelsModule)
    return getattr(modelsModule, modelName)

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

if settings.XGDS_DATA_LOG_ENABLED :
    class RequestLog(models.Model):
        timestampSeconds = models.DateTimeField(blank=False, default=datetime.utcnow())
        path = models.CharField(max_length=256, blank=False)
        ipaddress = models.CharField(max_length=256, blank=False)
        user = models.CharField(max_length=256, blank=False)  # probably can be a foreign key
        
        @classmethod
        def create(cls, request):
            rlog = cls(path=request.path,ipaddress=get_client_ip(request),user=request.user.__str__())
            return rlog
    
        def __unicode__(self):
            return 'Request %s:%s' % (self.id, self.path)
    
    class RequestArgument(models.Model):
        request = models.ForeignKey(RequestLog, null=False, blank=False)
        name = models.CharField(max_length=256, blank=False)
        value = models.TextField(blank=True)
        
    class ResponseLog(models.Model):
        timestampSeconds = models.DateTimeField(blank=False, default=datetime.utcnow())
        request = models.ForeignKey(RequestLog, null=False, blank=False)
        template = models.CharField(max_length=256, blank=True)
    
    class ResponseArgument(models.Model):
        response = models.ForeignKey(ResponseLog, null=False, blank=False)
        name = models.CharField(max_length=256, blank=False)
        value = models.CharField(max_length=1024, blank=True)
        
    class ResponseList(models.Model):
        response = models.ForeignKey(ResponseLog, null=False, blank=False)
        rank = models.PositiveIntegerField(blank=False)
        fclass = models.CharField(max_length=1024, blank=True)
        fid = models.PositiveIntegerField(blank=False)  # might be risky to assume this is always a pos int
