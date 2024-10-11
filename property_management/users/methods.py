from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers


def login_validate(request):
    phone = request.data.get('phone')
    password = request.data.get('password')
    if phone and password:
        user = authenticate(request=request, phone=phone, password=password)          #The authenticate call simply returns None for is_active=False
        if not user:
            msg = _('Unable to log in with provided credentials.')
            raise serializers.ValidationError(msg, code='authorization')
        return user
            
    else:
        msg = _('Must include phone and password.')
        raise serializers.ValidationError(msg, code='authorization')


def user_name_shown(user, default=None):           # like python .pop or .get second argument will return if dont found real data.  dont forget puting translations for default if needed for example  user_name_shown(user, gettex_lazy('admin'))   and run  django-admin makemessages -l fa   and add traslation of 'admin' in django.po and run  django-admin compilemessages
    if not isinstance(user, dict):
        try:
            if user.first_name and user.last_name:
                return '{} {}'.format(user.first_name, user.last_name)
            elif default:      # if user.first_name&last_name is False, return alternatives
                return default
            else:
                return str(user.phone.national_number)  # self.phone is not str (could raise error)
        except Exception as Ec:
            if default:       # if user.first_name&last_name fails (user is None), return alternatives
                return default
            else:
                return None

    try:         # for mongodb
        if user['first_name'] and user['last_name']:
            return '{} {}'.format(user['first_name'], user['last_name'])
        elif default:
            return default
        else:
            return str(user['phone'])
    except Exception as Ec:
        if default:  # if user.first_name&last_name fails (user is None), return alternatives
            return default
        else:
            return None
