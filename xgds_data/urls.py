# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from django.conf.urls.defaults import url, patterns

urlpatterns = patterns(
    'xgds_data.views',

    url(r'^search/$', 'searchIndex',
        name='xgds_data_searchIndex'),
    url(r'^search/(?P<modelName>[^/]+)/$', 'searchModel',
        name='xgds_data_searchModel'),                                      
    url(r'^chooseSearchModel/(?P<moduleName>[^/]+)/$', 'chooseSearchModel', 
        name='xgds_data_chooseSearchModel'),
    url(r'^searchChosenModel/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'searchChosenModel',
        name='xgds_data_searchChosenModel'),
    url(r'^plotQueryResults/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'plotQueryResults',
        name='xgds_data_plotQueryResults'),
)
