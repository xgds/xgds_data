# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

from django.conf.urls import url, patterns
from xgds_data import views

urlpatterns = patterns(
    'xgds_data.views',

    url(r'^$', views.index, name='index'),

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
    url(r'^search/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/(?P<expert>[^/]+)$', 'searchChosenModel',
        name='xgds_data_searchChosenModel'),
    url(r'^search/plot/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),
    url(r'^search/plot/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/(?P<start>\d+)/(?P<end>\d+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),
    url(r'^search/plot/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/(?P<soft>[^/]+)/(?P<start>\d+)/(?P<end>\d+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),

    url(r'^similar/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'searchSimilar',
        name='xgds_data_searchSimilar'),
    url(r'^similar/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/(?P<pkid>\d+)$', 'searchSimilar',
        name='xgds_data_searchSimilar'),

    # legacy urls
    url(r'^chooseSearchModel/(?P<moduleName>[^/]+)/$', 'chooseSearchModel',
        name='xgds_data_chooseSearchModel_orig'),
    url(r'^searchChosenModel/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/$', 'searchChosenModel',
        name='xgds_data_searchChosenModel_orig'),
)
