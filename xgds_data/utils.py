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

import datetime

def total_seconds(timediff):
    """Get total seconds for a time delta"""
    try:
        return timediff.total_seconds()
    except:
        return (timediff.microseconds + (timediff.seconds + timediff.days * 24 * 3600) * 10**6) / 10**6


def label(obj):
    """Figure out what to label this thing"""
    try:
        if (obj.last_name.strip() != '') and (obj.first_name.strip() != ''):
            return ', '.join([obj.last_name, obj.first_name])
        elif (obj.last_name.strip() != ''):
            return obj.last_name
        elif (obj.first_name.strip() != ''):
            return obj.first_name
        else:
            return unicode(obj)
    except AttributeError:
        return unicode(obj)


def handleFunnyCharacters(str):
    """
    Handle funny chars, if there are any. Databases don't like these.
    """
    try:
        return str.encode('utf-8', errors='ignore')
    except AttributeError:
        return str ## probably not a string


