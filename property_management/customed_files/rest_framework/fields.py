from rest_framework import serializers

from decimal import Decimal


persian_to_english = {
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
        '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9'}


class DecimalFile(serializers.CharField):
    def to_representation(self, value):
        if isinstance(value, Decimal):
            return str(value)
        else:
            return value


class ListSerializer(serializers.Field):  # simple field used to give/receive python list or...
    def to_internal_value(self, data):
        return data

    def to_representation(self, value):
        return value
