# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from django.conf.urls.defaults import url, patterns

urlpatterns = patterns(
    'xgds_data.views',

    url(r'^advancedSearch/$', 'searchIndex',
        name='xgds_data_searchIndex'),
    url(r'^advancedSearch/(?P<modelName>[^/]+)/$', 'searchModel',
        name='xgds_data_searchModel'),

    url(r'^search/$', 'chooseSearchApp',
        name='xgds_data_searchChooseApp'),
    url(r'^search/(?P<moduleName>[^/]+)/$', 'chooseSearchModel',
        name='xgds_data_searchChooseModel'),
    url(r'^search/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'searchChosenModel',
        name='xgds_data_searchChosenModel'),
    url(r'^search/plot/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),

    # legacy urls
    url(r'^chooseSearchModel/(?P<moduleName>[^/]+)/$', 'chooseSearchModel',
        name='xgds_data_chooseSearchModel_orig'),
    url(r'^searchChosenModel/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'searchChosenModel',
        name='xgds_data_searchChosenModel_orig'),
)
