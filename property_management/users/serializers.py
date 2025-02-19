from django.urls import reverse
from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

import jdatetime
import urllib.parse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User
from .methods import user_name_shown


class UserSerializer(serializers.ModelSerializer):  # used in CommentSerializer (mongodb)
    class Meta:
        model = User
        fields = '__all__'
    
    def to_representation(self, obj):
        self.fields['phone'] = serializers.SerializerMethodField()
        self.fields['date_joined'] = serializers.SerializerMethodField()  
        self.fields['last_login'] = serializers.SerializerMethodField()
        fields = super().to_representation(obj)
        [fields.pop(key, None) for key in ['groups', 'password', 'user_permissions', 'visible']]        #fields.pop(key, None)  this None means if dont find key for removing dont raise error return None instead.
        return fields

    def is_valid(self, raise_exception=False):
        assert hasattr(self, 'initial_data'), (
            'Cannot call `.is_valid()` as no `data=` keyword argument was '
            'passed when instantiating the serializer instance.'
        )

        if not hasattr(self, '_validated_data'):
            try:
                self._validated_data = self.run_validation(self.initial_data)
            except ValidationError as exc:
                self._validated_data = {}
                self._errors = exc.detail


                errors_dic = exc.detail.copy()
                for field_name in exc.detail:
                    for i in range(len(exc.detail[field_name])):
                        details_list = exc.detail[field_name].copy()          #exc.detail[field_name] is list and mutable with details, su we use .copy to stop changing exc.detail
                        details_list[i] = {exc.detail[field_name][i].code: exc.detail[field_name][i]}   #exc.detail[field_name][i] is object of ErrorDetail class
                    errors_dic[field_name] = details_list
                self._errors = {'error': exc.detail}


            else:
                self._errors = {}

        if self._errors and raise_exception:
            raise ValidationError(errors_dic)

        return not bool(self._errors)
    
    def get_phone(self, obj):
        return str(obj.phone.national_number)

    def get_date_joined(self, obj):
        return str(jdatetime.datetime.fromgregorian(datetime=obj.date_joined))

    def get_last_login(self, obj):
        if obj.last_login:                              # in first of user creation is None
            return str(jdatetime.datetime.fromgregorian(datetime=obj.last_login))


class UserChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ['password']


class UserNameSerializer(serializers.ModelSerializer):  # accept id as data (in write phase)
    url = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'url', 'user_name']

    def to_internal_value(self, data):
        if data:
            return get_object_or_404(User, id=data)

    def get_url(self, obj):
        if obj.is_staff:
            url = reverse('users:admin-profile', args=[obj.id])
            return urllib.parse.unquote(url)
        else:
            url = reverse('users:user-profile', args=[obj.id])
            return urllib.parse.unquote(url)

    def get_user_name(self, obj):
        return user_name_shown(obj, 'کاربر')


class TokenObtainPairSerializerCustom(TokenObtainPairSerializer):
    def validate(self, attrs):
        # Extract phone and password from the incoming data
        phone, password = attrs.get('phone'), attrs.get('password')
        user = authenticate(request=self.context['request'], phone=phone, password=password)
        if not user:
            raise AuthenticationFailed('Invalid phone or password.')
        # Generate token using the parent class logic
        data = super().validate(attrs)   # contain: {'refresh': ..., 'access': ...}
        data['user'] = {'id': user.id, 'phone': str(user.phone)}
        return data
