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
    url(r'^advancedSearch/(?P<searchModelName>[^/]+)/$', 'searchModel',
        name='xgds_data_searchModel'),

    url(r'^search/$', 'chooseSearchApp',
        name='xgds_data_searchChooseApp'),
    url(r'^search/(?P<searchModuleName>[^/]+)/$', 'chooseSearchModel',
        name='xgds_data_searchChooseModel'),
    url(r'^search/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/$', 'searchChosenModel',
        name='xgds_data_searchChosenModel'),
    url(r'^search/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<expert>[^/]+)$', 'searchChosenModel',
        name='xgds_data_searchChosenModel'),
    url(r'^search/plot/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),
    url(r'^search/plot/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<soft>[^/]+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),
    url(r'^search/plot/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<start>\d+)/(?P<end>\d+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),
    url(r'^search/plot/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<soft>[^/]+)/(?P<start>\d+)/(?P<end>\d+)/$', 'plotQueryResults',
        name='xgds_data_searchPlotQueryResults'),
    url(r'^display/(?P<displayModuleName>[^/]+)/(?P<displayModelName>[^/]+)/(?P<rid>[^/]+)$', 'displayRecord', name='xgds_data_displayRecord'),
#    url(r'^edit/(?P<editModuleName>[^/]+)/(?P<editModelName>[^/]+)/(?P<rid>[^/]+)$', 'editRecord', name='xgds_data_editRecord'),

    url(r'^similar/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/$', 'searchSimilar',
        name='xgds_data_searchSimilar'),
    url(r'^similar/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<pkid>\d+)$', 'searchSimilar',
        name='xgds_data_searchSimilar'),

    url(r'^replayRequest/(?P<rid>\d+)$', 'replayRequest', name='xgds_data_replayRequest'),

    # legacy urls
    #url(r'^chooseSearchModel/(?P<searchModuleName>[^/]+)/$', 'chooseSearchModel',
    #    name='xgds_data_chooseSearchModel_orig'),
    #url(r'^searchChosenModel/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/$', 'searchChosenModel',
    #    name='xgds_data_searchChosenModel_orig'),
)
