# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import sys

# from django.db import models

# from xgds_data import settings


def getModelByName(name):
    appName, modelName = name.split('.', 1)
    modelsName = appName + '.models'
    __import__(modelsName)
    modelsModule = sys.modules[modelsName]
    print modelsModule
    print dir(modelsModule)
    return getattr(modelsModule, modelName)
