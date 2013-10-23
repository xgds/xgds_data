from xgds_data import settings

def logEnabled():
    return (hasattr(settings, 'XGDS_DATA_LOG_ENABLED') and
            settings.XGDS_DATA_LOG_ENABLED)
