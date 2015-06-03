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

from datetime import datetime

from django.db import models
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic                                 
from django.core.urlresolvers import reverse

from xgds_data import settings
from xgds_data.logconfig import logEnabled
#from xgds_data.introspection import modelFields
import xgds_data.introspection


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


class GenericLink(models.Model):
    linkType = models.ForeignKey(ContentType, null=True, blank=True)
    linkId = models.PositiveIntegerField(null=True, blank=True)
    link = generic.GenericForeignKey('linkType', 'linkId') 

    def get_absolute_url(self):
        return reverse('xgds_data_displayRecord',
                       args=[xgds_data.introspection.moduleName(self.link),
                             xgds_data.introspection.modelName(self.link),
                             xgds_data.introspection.pkValue(self.link)])

    def __unicode__(self):
        return self.link.__unicode__()


class Collection(models.Model):
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=1024)
    contents = models.ManyToManyField(GenericLink)

    def get_edit_url(self):
        return reverse('xgds_data_editCollection',
                       args=[xgds_data.introspection.pkValue(self)])

    def resolvedContents(self):
        return [x.link for x in self.contents.all() if x.link is not None]

class VirtualIncludedField(models.Field):
    description = "Including fields from a linked object as if they were your own"

    def __init__(self, mymodel, throughfield_name, base_name, base_verbose_name, *args, **kwargs):
        super(VirtualIncludedField, self).__init__(*args, **kwargs)
        self.model = mymodel
        self.throughfield_name = throughfield_name
        self.name = base_name
        self.verbose_name = base_verbose_name

    def throughModels(self):
        match = None
        for f in xgds_data.introspection.modelFields(self.model):
            if f.name == self.throughfield_name:
                match = f
        if (match is not None):
            try:
                throughmodels = [ContentType.objects.get_for_id(x[0]).model_class()
                                 for x in self.model.objects.values_list(match.ct_field).distinct()]
            except:  # not a GenericForeignKey
                # this route has never been tested
                throughmodels = [match.rel.to]
            return throughmodels
        else:
            return []

    def targetFields(self):
        targets = []
        for tm in self.throughModels():
            for tmf in xgds_data.introspection.modelFields(tm):
                if tmf.name == self.name:
                    targets.append(tmf)
        return targets

    def isgeneric(self):
        return True


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
        timestampSeconds = models.DateTimeField(verbose_name="Time", blank=False)
        path = models.CharField(max_length=256, blank=False)
        ipaddress = models.CharField(max_length=256, blank=False)
        #user = models.CharField(max_length=64, blank=False)  # probably can be a foreign key
        user = models.ForeignKey(User, null=True, blank=True)
        session = models.CharField(max_length=64, null=True, blank=True)
        referer = models.CharField(max_length=256, null=True, blank=True)
        user_agent = models.CharField(max_length=256, null=True, blank=True)

        def get_absolute_url(self):
            return reverse('xgds_data_replayRequest', args=[self.id])

        @classmethod
        def create(cls, request):
            ref = request.META.get('HTTP_REFERER', None)
            uagent = request.META.get('HTTP_USER_AGENT', None)
            uzer = request.user
            if uzer.id is None:
                uzer = None

            # rlog = cls(path=request.path, ipaddress=get_client_ip(request), user=request.user.__str__())
            rlog = cls(timestampSeconds=datetime.utcnow(),
                       path=truncate(request.path, 256),
                       ipaddress=truncate(get_client_ip(request), 256),
                       user=uzer,
                       session=truncate(request.session.session_key, 64),
                       referer=truncate(ref, 256),
                       user_agent=truncate(uagent, 256))
            return rlog

        def __unicode__(self):
            stuff = self.path.rstrip('/').split('/')
            return stuff[len(stuff)-1]

    class RequestArgument(models.Model):
        request = models.ForeignKey(RequestLog, null=False, blank=False)
        name = models.CharField(max_length=256, blank=False)
        value = models.TextField(blank=True)

        def __unicode__(self):
            return '%s = %s' % (self.name, self.value)

    class ResponseLog(models.Model):
        timestampSeconds = models.DateTimeField(blank=False)
        request = models.ForeignKey(RequestLog, null=False, blank=False)
        template = models.CharField(max_length=256, blank=True)

        @classmethod
        def create(cls, request, template=None):
            if (template is None):
                return cls(timestampSeconds=datetime.utcnow(), request=request)
            else:
                return cls(timestampSeconds=datetime.utcnow(), request=request, template=template)

        def __unicode__(self):
            return 'Response %s:%s' % (self.id, self.template)

    class ResponseArgument(models.Model):
        response = models.ForeignKey(ResponseLog, null=False, blank=False)
        name = models.CharField(max_length=256, blank=False)
        value = models.CharField(max_length=1024, blank=True)

        def __unicode__(self):
            return '%s=%s' % (self.name, self.value)

    class ResponseList(models.Model):
        response = models.ForeignKey(ResponseLog, null=False, blank=False)
        rank = models.PositiveIntegerField(blank=False)
        fclass = models.CharField(max_length=1024, blank=True)
        fid = models.PositiveIntegerField(blank=False)  # might be risky to assume this is always a pos int

        def __unicode__(self):
            return '%s #%s' % (self.fclass, self.fid)

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
