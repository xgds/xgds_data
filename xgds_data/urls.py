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

from django.views.generic import TemplateView
from django.conf.urls import url
from django.conf import settings
from xgds_data import views

urlpatterns = [
    url(r'^$', views.index, name='xgds_data_index'),

    # url(r'^advancedSearch/$', 'searchIndex',
    #     name='xgds_data_searchIndex'),
    # url(r'^advancedSearch/(?P<searchModelName>[^/]+)/$', 'searchModel',
    #     name='xgds_data_searchModel'),

    ## Searching
    url(r'^search/$', views.chooseSearchApp,
        name='xgds_data_searchChooseApp'),
    url(r'^search/(?P<searchModuleName>[^/]+)/$', views.chooseSearchModel,
        name='xgds_data_searchChooseModel'),

    url(r'^search/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/$',
        views.searchChosenModel, name='xgds_data_searchChosenModel'),
    url(r'^search/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<expert>[^/]+)$',
        views.searchChosenModel,name='xgds_data_searchChosenModel'),

    url(r'^similar/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<pkid>[^/]+)$',
        views.searchSimilar, name='xgds_data_searchSimilar'),


    ## Plotting
    url(r'^retrieve/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<field>[^/]*)$',
        views.getFieldValues, name='xgds_data_getFieldValues'),
    url(r'^retrieve/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<field>[^/]+)/(?P<soft>[^/]+)/*$',
        views.getFieldValues, name='xgds_data_getFieldValues'),
    url(r'^search/plot/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/$',
        views.plotQueryResults, name='xgds_data_searchPlotQueryResults'),
    url(r'^search/plot/(?P<searchModuleName>[^/]+)/(?P<searchModelName>[^/]+)/(?P<soft>[^/]+)/*$',
        views.plotQueryResults, name='xgds_data_searchPlotQueryResults'),


    ## displaying
    url(r'^display/(?P<displayModuleName>[^/]+)/(?P<displayModelName>[^/]+)/(?P<rid>[^/]*)$',
        views.displayRecord, name='xgds_data_displayRecord'),
    url(r'^display/(?P<displayModuleName>[^/]+)/(?P<displayModelName>[^/]+)/(?P<rid>[^/]*)/(?P<force>[^/]*)$',
        views.displayRecord, name='xgds_data_displayRecord'),


    ## Handling collections
    url(r'^group/(?P<groupModuleName>[^/]+)/$',
        views.chooseGroupModel, name='xgds_data_groupChooseModel'),
    url(r'^group/(?P<groupModuleName>[^/]+)/(?P<groupModelName>[^/]+)/$',
        views.createCollection, name='xgds_data_createCollection'),
    url(r'^group/(?P<groupModuleName>[^/]+)/(?P<groupModelName>[^/]+)/(?P<expert>[^/]+)$',
        views.createCollection, name='xgds_data_createCollection'),
    url(r'^editCollection/(?P<rid>[^/]+)$',
        views.editCollection, name='xgds_data_editCollection'),
    url(r'^collectionContents/(?P<rid>[^/]+)$',
        views.getCollectionContents, name='xgds_data_getCollectionContents'),


    ## showing past action again
    url(r'^replayRequest/(?P<rid>\d+)$',
        views.replayRequest, name='xgds_data_replayRequest'),


    ## uploading data
    url(r'^import/$', TemplateView.as_view(template_name='xgds_data/importData.html'), name='xgds_data_import'),
]

try:
    if settings.XGDS_DATA_EDITING:
        urlpatterns += [
                                ## Editing
                                url(r'^edit/(?P<editModuleName>[^/]+)/(?P<editModelName>[^/]+)/(?P<rid>[^/]+)$',
                                    views.editRecord, name='xgds_data_editRecord'),

                                ## Deleting
                                url(r'^delete/(?P<deleteModuleName>[^/]+)/$',
                                    views.chooseDeleteModel,
                                    name='xgds_data_deleteChooseModel'),
                                url(r'^delete/(?P<deleteModuleName>[^/]+)/(?P<deleteModelName>[^/]+)/*$',
                                    views.deleteRecord,
                                    name='xgds_data_deleteRecord'),
                                url(r'^delete/(?P<deleteModuleName>[^/]+)/(?P<deleteModelName>[^/]+)/(?P<rid>[^/]+)$',
                                    views.deleteRecord,
                                    name='xgds_data_deleteRecord'),

                                url(r'^deleteMultiple/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/*$',
                                    views.deleteMultiple,
                                    name='xgds_data_deleteMultiple'),
                                url(r'^deleteMultiple/(?P<moduleName>[^/]+)/(?P<modelName>[^/]+)/(?P<expert>[^/]+)/*$',
                                    views.deleteMultiple,
                                    name='xgds_data_deleteMultiple'),


                                ## Creating
                                url(r'^create/(?P<createModuleName>[^/]+)/$',
                                    views.chooseCreateModel,
                                    name='xgds_data_createChooseModel'),

                                url(r'^create/(?P<createModuleName>[^/]+)/(?P<createModelName>[^/]+)/$',
                                    views.createChosenModel,
                                    name='xgds_data_createChosenModel'),

        ]
except AttributeError:
    pass
