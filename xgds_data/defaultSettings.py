# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

"""
This app may define some new parameters that can be modified in the
Django settings module.  Let's say one such parameter is XGDS_DATA_FOO.
The default value for XGDS_DATA_FOO is defined in this file, like this:

  XGDS_DATA_FOO = 'my default value'

If the admin for the site doesn't like the default value, they can
override it in the site-level settings module, like this:

  XGDS_DATA_FOO = 'a better value'

Other modules can access the value of FOO like this:

  from xgds_data import settings
  print settings.XGDS_DATA_FOO

Don't try to get the value of XGDS_DATA_FOO from django.conf.settings.
That settings object will not know about the default value!
"""

# choose models to support in siteSettings.py
XGDS_DATA_SEARCH_MODELS = ()
