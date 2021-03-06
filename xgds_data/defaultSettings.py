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

from geocamUtil.SettingsUtil import getOrCreateArray, getOrCreateDict

"""
This app may define some new parameters that can be modified in the
Django settings module.  Let's say one such parameter is XGDS_DATA_FOO.
The default value for XGDS_DATA_FOO is defined in this file, like this:

  XGDS_DATA_FOO = 'my default value'

If the admin for the site doesn't like the default value, they can
override it in the site-level settings module, like this:

  XGDS_DATA_FOO = 'a better value'

Other modules can access the value of FOO like this:

  from django.conf import settings
  print settings.XGDS_DATA_FOO

Don't try to get the value of XGDS_DATA_FOO from django.conf.settings.
That settings object will not know about the default value!
"""

# choose models to support in siteSettings.py. mostly obsolete.
XGDS_DATA_SEARCH_MODELS = ()

# choose django apps not to list for search purposes
XGDS_DATA_SEARCH_SKIP_APP_PATTERNS = (
    r'^django\..*',
    r'^geocam.*',
    r'^pipeline$',
)

# XGDS_DATA_LOG_ENABLED = False

XGDS_DATA_MAX_PULLDOWNABLE = 100
XGDS_DATA_MAX_SERIESABLE = 100

# possible fields to treat as the 'primary time field' for a model.
# try in order until the model has one of the fields.
XGDS_DATA_TIME_FIELDS = (
    'timestampSeconds',
    'timeStampSeconds',
    'timestamp',
)

XGDS_DATA_MASKED_FIELDS = getOrCreateDict('XGDS_DATA_MASKED_FIELDS')
XGDS_DATA_MASKED_FIELDS['auth']= {'User': ['password', 'is_staff', 'is_active', 'is_superuser',
                                           'last_login',
                                           'date_joined', 'groups', 'user_permissions',
                                           ],
                                  }

XGDS_DATA_EXPAND_RELATED = getOrCreateDict('XGDS_DATA_EXPAND_RELATED')
XGDS_DATA_EXPAND_RELATED['xgds_data'] = {'RequestLog': [('requestargument_set', 'all', 'Arguments'),
                                                        ('responselog_set', 'all', 'Response'),
                                                        ],
                                         'ResponseLog': [('responseargument_set', 'all', 'Arguments'),
                                                         ('responselist_set', 'all', 'Results'),
                                                         ],
                                         'Collection': [ (None,'contents','Contents'),
                                                        ] ,   
                                         }
