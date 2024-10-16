from django.urls import reverse
from django.conf import settings
from django.utils.text import slugify
from django.shortcuts import get_object_or_404
from django.core.files.storage import default_storage
from django.core.validators import MaxLengthValidator
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers
from rest_framework.fields import empty

import os
import re
import uuid
import pymongo
import environ
import jdatetime
import urllib.parse
from urllib.parse import quote_plus
from pathlib import Path
from bson.objectid import ObjectId
from decimal import Decimal
from onetomultipleimage.fields import OneToMultipleImage
from onetomultipleimage.methods import ImageCreationSizes
from mongoserializer.serializer import MongoSerializer, MongoListSerializer
from mongoserializer.fields import TimestampField, IdMongoField
from mongoserializer.methods import save_to_mongo as general_save_to_mongo
from drf_extra_fields.fields import Base64ImageField

from .models import *
from .methods import comment_save_to_mongo, get_category_and_fathers
from customed_files.rest_framework.classes.validators import MongoUniqueValidator
from customed_files.rest_framework.fields import DecimalFile
from users.serializers import UserNameSerializer
from users.methods import user_name_shown
from users.models import User

env = environ.Env()
environ.Env.read_env(os.path.join(Path(__file__).resolve().parent.parent.parent, '.env'))
username, password, db_name = quote_plus(env('MONGO_USER_NAME')), quote_plus(env('MONGO_USER_PASS')), env('MONGO_DBNAME')
auth_source, host = env('MONGO_SOURCE'), env('MONGO_HOST')
uri = f"mongodb://{username}:{password}@{host}:27017/{db_name}?authSource={auth_source}"
mongo_db = pymongo.MongoClient(uri)[db_name]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


# receive one cat list 'samsung', returns several cat: 'digital' > 'phone' > 'samsung'
class CategoryFathersChainedSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Category
        fields = ['name', 'url']

    def __new__(cls, instance=None, revert=None, *args, **kwargs):
        if instance and kwargs.get('many'):
            cats = get_category_and_fathers(instance)
            if revert:
                cats.reverse()
            return super().__new__(cls, cats, **kwargs)
        return super().__new__(cls, *args, **kwargs)

    def get_url(self, obj):
        url = reverse('main:products-list-cat', args=[1, obj.slug]) if obj.post_product == 'products' else reverse('main:posts-list-cat', args=[1, obj.slug])
        return urllib.parse.unquote(url)


class ReplySerializer(serializers.ModelSerializer):  # not implemented
    pass


class CommentListSerializer(MongoListSerializer):
    def update(self, _id, serialized):  # _id and serialized are both list
        updates = []
        for comment_id, comment_data in zip(_id, serialized):
            update_set = {f'comments.$.{key}': comment_data[key] for key in comment_data}
            updates.append(pymongo.UpdateOne(
                {'_id': ObjectId(self.father_id), 'comments._id': ObjectId(comment_id)},
                {'$set': update_set}
            ))

        self.mongo_collection.bulk_write(updates)
        return serialized


statuses = [('1', _('not checked')), ('2', _('confirmed')), ('3', _('not confirmed')), ('4', _('deleted'))]
class CommentSerializer(MongoSerializer):
    _id = IdMongoField(mongo_update=True, required=False)   # in creation automatically generates _id in to_internal
    username = serializers.CharField(max_length=30, default='کاربر')  # 'name' raise error! (when is inside )
    email = serializers.EmailField(required=False)
    status = serializers.ChoiceField(choices=statuses, default='1')
    published_date = TimestampField(jalali=True, auto_now_add=True, required=False)
    content = serializers.CharField(validators=[MaxLengthValidator(500)])
    post = serializers.CharField(max_length=255, required=False)  # mongo _id
    product = serializers.CharField(max_length=255, required=False)  # mongo _id
    author = UserNameSerializer(required=False, read_only=True)  # fills in to_internal_value
    reviewer = UserNameSerializer(required=False, read_only=True)
    # replies = serializers.SerializerMethodField(required=False)  # not implemented

    class Meta:
        list_serializer_class = CommentListSerializer

    def __init__(self, _id=None, request=None, **kwargs):
        # request use to fill .author (in writing), otherwise should provide author explicitly (in data)
        # instance and pk should not conflict in updating and retrieving like: updating: serializer(pk=1, data={..}),
        # retrieving: serializer(instance).data
        if kwargs.get('partial'):      # in updating only provided fields should validate
            for key in self.fields:
                self.fields[key].required = False
        super().__init__(_id=_id, request=request, **kwargs)

    def to_internal_value(self, data):
        request, change = self.context.get('request') or self.request, self.context.get('change', False)

        if not change and not data.get('username'):
            data['username'] = user_name_shown(request.user, 'کاربر') if request.user else 'کاربر'

        internal_value = super().to_internal_value(data)

        if not change:
            internal_value['_id'] = ObjectId()

        if request and request.user and not change:  # in updating, user is not required
            internal_value['author'] = request.user
        elif data.get('author'):
            internal_value['author'] = get_object_or_404(User, id=data['author'])
        elif not change:
            raise ValidationError({'author': "please login and pass 'request' parameter or add user id manually"})

        if data.get('reviewer'):
            internal_value['reviewer'] = get_object_or_404(User, id=data['reviewer'])
        return internal_value

    def field_filtering_for_update(self, input, output):  # input=validated_data, output=serializer.data or..
        # keep only fields provided in validated_data and remove unexpected others
        for key in output.copy():
            if key not in input:
                del output[key]
        return output

    def get__id(self, obj):
        return obj['_id']

    def get_replies(self, obj):
        pass


class OneToMultipleImageMongo(OneToMultipleImage, MongoSerializer):
    _id = IdMongoField(mongo_update=True, required=False)

    def update(self, _id, serialized):
        if serialized[0].get('image'):
            # in update or create phase, if 'image' data provided, refill whole 'icon' field again in db
            serialized = [{'_id': id, **dct} for id, dct in zip(_id, serialized)]
            self.mongo_collection.update_one({'_id': ObjectId(self.father_id)},
                                             {'$set': {'icon': serialized}})
        else:
            for id, icon in zip(_id, serialized):
                update_set = {f'icon.$.{key}': icon[key] for key in icon}
                updates = []
                updates.append(pymongo.UpdateOne(
                    {'_id': ObjectId(self.father_id), 'icon._id': ObjectId(id)},
                    {'$set': update_set}
                ))
            self.mongo_collection.bulk_write(updates)
        return serialized

    def to_internal_value(self, data):
        change = self.context.get('change', False)
        internal_value = super().to_internal_value(data)    # internal_value returned by 'OneToMultipleImage' is list
        if internal_value and not change and internal_value[0].get('image'):  # internal_value can be blank list
            # in update or create phase, if 'image' data provided, refill whole 'icon' field again in db
            for dct in internal_value:
                dct['_id'] = ObjectId()
        return internal_value


class ImageListSerializer(MongoListSerializer):
    def update(self, _id, serialized):  # _id and serialized are both list
        if _id:         # update images
            updates = []
            for id, data in zip(_id, serialized):
                update_set = {f'images.$.{key}': data[key] for key in data}
                id = id if isinstance(id, ObjectId) else ObjectId(id)  # id's type is usually ObjectId
                updates.append(pymongo.UpdateOne({'_id': ObjectId(self.father_id), 'images._id': id}, {'$set': update_set}))

            self.mongo_collection.bulk_write(updates)
            return serialized
        else:         # add images (for example to the post.images)
            try:
                mongo_collection = self.mongo_collection
                for image in serialized:
                    image['_id'] = ObjectId()
                    mongo_collection.update_one({'_id': ObjectId(self.father_id)}, {'$push': {'images': image}})
                return serialized
            except:
                raise        # raise default python error


class ImageSerializer(MongoSerializer):
    # image can be url too (like: 'http:....')
    _id = IdMongoField(mongo_update=True, required=False)
    name = serializers.CharField(max_length=100, required=False)
    image = serializers.CharField(allow_null=True, required=False)  # image can be url('http..')|Base64|python open
    alt = serializers.CharField(max_length=100, allow_blank=True, default='')

    class Meta:
        list_serializer_class = ImageListSerializer

    def __init__(self, instance=None, upload_to=None, *args, **kwargs):
        super().__init__(instance, *args, **kwargs)
        self.upload_to = upload_to

    def to_representation(self, instance):
        img = instance.get('image')
        if img and not isinstance(img, str):   # img is not url
            instance['image'] = img.url
        return super().to_representation(instance)

    def to_internal_value(self, data):
        change = self.context.get('change', False)
        internal_value = super().to_internal_value(data)
        img = data.get('image')
        if img:
            if isinstance(img, str) and img.startswith('http'):
                pass
            else:
                obj = ImageCreationSizes(data={'image': data['image'], 'alt': data.get('alt', '')},
                                         sizes=['default'], name=data.get('name'))
                img = obj.upload(upload_to=self.upload_to)[0]
            internal_value['image'] = img
        return internal_value

    def update(self, _id, serialized):
        update_set = {f'images.$.{key}': serialized[key] for key in serialized}
        self.mongo_collection.update_one({'_id': ObjectId(self.father_id), 'images._id': _id}, {'$set': update_set})
        return serialized


# don't use this for representation like: PostMongoSerializer(DictToObject(post_col)).data
# in updating must be like: PostMongoSerializer(pk=1, data=data, partial=True, request=request)
# in creation: PostMongoSerializer(data=data, prequest=request)
class PostMongoSerializer(MongoSerializer):
    # [title, brief_description, request.user/author required
    trades = [('1', _('rent')), ('2', _('sale'))]
    presents = [('1', _('new')), ('2', _('open')), ('3', _('hot'))]

    title = serializers.CharField(label=_('title'), validators=[MongoUniqueValidator(mongo_db.post, 'title')], max_length=255)
    slug = serializers.SlugField(label=_('slug'), allow_unicode=True, required=False)    # slug generates from title (in to_internal_value)
    published_date = TimestampField(label=_('published date'), auto_now_add=True, jalali=True, required=False)
    updated = TimestampField(label=_('updated date'), jalali=True, auto_now=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=30), default=[])
    meta_title = serializers.CharField(allow_blank=True, max_length=60, required=False)
    meta_description = serializers.CharField(allow_blank=True, required=False, validators=[MaxLengthValidator(160)])
    brief_description = serializers.CharField(validators=[MaxLengthValidator(1000)])
    detailed_description = serializers.CharField(allow_blank=True, required=False)
    instagram_link = serializers.CharField(allow_blank=True, max_length=255, required=False)
    visible = serializers.BooleanField(default=True)
    author = UserNameSerializer(required=False)  # author can fill auto in to_internal_value, otherwise must input
    icon = OneToMultipleImageMongo(sizes=['240', '420', '640', '720', '960', '1280', 'default'], upload_to='post_images/icons/', required=False)
    category_fathers = serializers.SerializerMethodField()
    category = CategorySerializer(required=False, read_only=True)  # it's validated_data fill in 'to_internal_value'
    comments = CommentSerializer(many=True, required=False)

    @property
    def context(self):
        return self._context

    @context.setter
    def context(self, value):      # default .context have no setter so should define manually
        self._context = value

    def __init__(self, instance=None, pk=None, *args, **kwargs):
        super().__init__(instance, pk, *args, **kwargs)
        self.context.update({'change': not bool(pk)})

    def to_internal_value(self, data):
        if not data.get('slug') and data.get('title'):
            data['slug'] = slugify(data['title'], allow_unicode=True)  # data==request.data==self.initial_data mutable
        internal_value = super().to_internal_value(data)

        if data.get('category'):
            level = Category.objects.filter(id=data['category']).values_list('level', flat=True)[0]
            related = 'father_category'
            # '__father_category' * -1 == '', prefetch_related('child_categories') don't need because of single category
            i = Category._meta.get_field('level').validators[1].limit_value-1-level  # raise error when use directly!
            related += '__father_category' * i
            cat = Category.objects.filter(id=data['category']).select_related(related)[0]
            internal_value['category_fathers'] = cat
            internal_value['category'] = cat

        request = self.context.get('request')
        if request:
            if request.user:
                internal_value['author'] = request.user
            else:
                raise ValidationError({'author': 'please login to fill post.author'})
        elif data.get('author'):
            internal_value['author'] = get_object_or_404(User, id=data['author'])
        else:
            raise ValidationError({'author': "please login and pass 'request' parameter or add user id manually"})

        return internal_value

    def create(self, collection):
        data = self.serialize_and_filter(self.validated_data)
        return general_save_to_mongo(mongo_db.post, data=data)

    def get_category_fathers(self, obj):
        if getattr(obj, 'category', None):
            return CategoryFathersChainedSerializer(obj.category, revert=True, many=True).data


class PostListSerializer(serializers.Serializer):
    _id = IdMongoField(required=False)
    title = serializers.CharField(label=_('title'), max_length=255)
    slug = serializers.SlugField(label=_('slug'), allow_unicode=True, required=False)    # slug generates from title (in to_internal_value)
    published_date = TimestampField(label=_('published date'), jalali=True, required=False)
    updated = TimestampField(label=_('updated date'), jalali=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=30), default=[])
    meta_title = serializers.CharField(allow_blank=True, max_length=60, required=False)
    meta_description = serializers.CharField(allow_blank=True, required=False, validators=[MaxLengthValidator(160)])
    brief_description = serializers.CharField(validators=[MaxLengthValidator(1000)])
    url = serializers.SerializerMethodField()  # show simple str before data/list (in serializer(...).data)
    author = serializers.SerializerMethodField()  # author will fill auto from request.user, otherwise must input
    icon = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()  # it's validated_data fill in 'to_internal_value'

    def get_url(self, obj):
        pk, slug = str(obj._id), obj.slug
        return urllib.parse.unquote(reverse('main:post_detail', args=[pk, slug]))

    def get_author(self, obj):
        if getattr(obj, 'author', None):
            author = obj.author
            if author:
                url = urllib.parse.unquote(reverse('users:admin-profile', args=[author.id]))
                return {'url': url, 'user_name': author.user_name}

    def get_icon(self, obj):
        if getattr(obj, 'icon', None):
            icon, result = obj.icon, {}
            if icon:
                for size in icon:
                    ic = icon[size]
                    result[size] = {'image': ic.image, 'alt': ic.alt}
                return result

    def get_category(self, obj):
        if getattr(obj, 'category', None):
            cat = obj.category
            name = cat.name
            url = urllib.parse.unquote(reverse('main:posts-list-cat', args=[1, cat.slug]))
        else:
            name, url = ('', '')
        return {'name': name, 'url': url}


class FileListMongoSerializer(MongoListSerializer):
    # example usage (single and list):
    # data_update = {'title': uuid.uuid4().hex[:2], 'images': [{'_id': '67012184cc642f46deced213', 'alt': 'OOO'}]}
    # FileMongoSerializer(_id='67012184...', data=data_update, request=request, partial=True)
    # FileMongoSerializer(_id=['67012184...'], data=[data_update], request=request, many=True, partial=True)
    def update(self, _id, validated_data):
        # update fields
        list_of_serialized = super().update(_id, validated_data)
        updates = []
        for _id, data in zip(_id, list_of_serialized):  # nested fields updated in their own classes
            update_set = {key: value for key, value in data.items()}
            updates.append(pymongo.UpdateOne({'_id': ObjectId(_id)}, {"$set": update_set}))
        self.mongo_collection.bulk_write(updates)
        return list_of_serialized


neighborhoods_ch = {5: {'id': 5, 'NeighborhoodName': 'آجودانیه', 'Areaid': 1}, 6: {'id': 6, 'NeighborhoodName': 'آبک', 'Areaid': 1}, 7: {'id': 7, 'NeighborhoodName': 'احتسابیه', 'Areaid': 1}, 8: {'id': 8, 'NeighborhoodName': 'اراج', 'Areaid': 1}, 9: {'id': 9, 'NeighborhoodName': 'ازگل', 'Areaid': 1}, 10: {'id': 10, 'NeighborhoodName': 'اقدسیه', 'Areaid': 1}, 11: {'id': 11, 'NeighborhoodName': 'الهیه', 'Areaid': 1}, 12: {'id': 12, 'NeighborhoodName': 'تجریش', 'Areaid': 1}, 13: {'id': 13, 'NeighborhoodName': 'زعفرانیه', 'Areaid': 1}, 14: {'id': 14, 'NeighborhoodName': 'سعدآباد', 'Areaid': 1}, 15: {'id': 15, 'NeighborhoodName': 'فرمانیه', 'Areaid': 1}, 16: {'id': 16, 'NeighborhoodName': 'قیطریه', 'Areaid': 1}, 17: {'id': 17, 'NeighborhoodName': 'کامرانیه', 'Areaid': 1}, 18: {'id': 18, 'NeighborhoodName': 'نیاوران', 'Areaid': 1}, 19: {'id': 19, 'NeighborhoodName': 'ولنجک', 'Areaid': 1}, 20: {'id': 20, 'NeighborhoodName': 'کاشانک', 'Areaid': 1}, 21: {'id': 21, 'NeighborhoodName': 'سامیان', 'Areaid': 1}, 22: {'id': 22, 'NeighborhoodName': 'دربند', 'Areaid': 1}, 23: {'id': 23, 'NeighborhoodName': 'اوین', 'Areaid': 1}, 24: {'id': 24, 'NeighborhoodName': 'باغ فردوس', 'Areaid': 1}, 25: {'id': 25, 'NeighborhoodName': 'جماران', 'Areaid': 1}, 26: {'id': 26, 'NeighborhoodName': 'چیذر', 'Areaid': 1}, 29: {'id': 29, 'NeighborhoodName': 'تهران ویلا', 'Areaid': 2}, 30: {'id': 30, 'NeighborhoodName': 'ستارخان', 'Areaid': 2}, 31: {'id': 31, 'NeighborhoodName': 'سعادت اباد', 'Areaid': 2}, 32: {'id': 32, 'NeighborhoodName': 'شهرک غرب', 'Areaid': 2}, 33: {'id': 33, 'NeighborhoodName': 'شهرآرا', 'Areaid': 2}, 34: {'id': 34, 'NeighborhoodName': 'صادقیه', 'Areaid': 2}, 35: {'id': 35, 'NeighborhoodName': 'طرشت', 'Areaid': 2}, 36: {'id': 36, 'NeighborhoodName': 'فرحزاد', 'Areaid': 2}, 37: {'id': 37, 'NeighborhoodName': 'گیشا', 'Areaid': 2}, 38: {'id': 38, 'NeighborhoodName': 'همایونشهر', 'Areaid': 2}, 39: {'id': 39, 'NeighborhoodName': 'مرزداران', 'Areaid': 2}, 41: {'id': 41, 'NeighborhoodName': 'اختیاریه', 'Areaid': 1}, 42: {'id': 42, 'NeighborhoodName': 'پاسداران', 'Areaid': 1}, 43: {'id': 43, 'NeighborhoodName': 'دروس', 'Areaid': 1}, 44: {'id': 44, 'NeighborhoodName': 'دولت', 'Areaid': 3}, 45: {'id': 45, 'NeighborhoodName': 'دیباجی', 'Areaid': 3}, 46: {'id': 46, 'NeighborhoodName': 'سیدخندان', 'Areaid': 7}, 47: {'id': 47, 'NeighborhoodName': 'ظفر', 'Areaid': 3}, 48: {'id': 48, 'NeighborhoodName': 'قلهک', 'Areaid': 3}, 49: {'id': 49, 'NeighborhoodName': 'میرداماد', 'Areaid': 3}, 50: {'id': 50, 'NeighborhoodName': 'ونک', 'Areaid': 3}, 52: {'id': 52, 'NeighborhoodName': 'حکیمیه', 'Areaid': 4}, 53: {'id': 53, 'NeighborhoodName': 'سراج', 'Areaid': 4}, 54: {'id': 54, 'NeighborhoodName': 'شمران نو', 'Areaid': 4}, 55: {'id': 55, 'NeighborhoodName': 'علم و صنعت', 'Areaid': 4}, 56: {'id': 56, 'NeighborhoodName': 'فرجام', 'Areaid': 4}, 57: {'id': 57, 'NeighborhoodName': 'قنات کوثر', 'Areaid': 4}, 59: {'id': 59, 'NeighborhoodName': 'نارمک شرقی', 'Areaid': 8}, 60: {'id': 60, 'NeighborhoodName': 'هروی', 'Areaid': 4}, 61: {'id': 61, 'NeighborhoodName': 'هنگام', 'Areaid': 4}, 62: {'id': 62, 'NeighborhoodName': 'تهرانپارس غربی', 'Areaid': 4}, 63: {'id': 63, 'NeighborhoodName': 'تهرانپارس شرقی', 'Areaid': 4}, 66: {'id': 66, 'NeighborhoodName': 'شیان', 'Areaid': 4}, 67: {'id': 67, 'NeighborhoodName': 'لویزان', 'Areaid': 4}, 68: {'id': 68, 'NeighborhoodName': 'مجیدیه شمالی', 'Areaid': 4}, 70: {'id': 70, 'NeighborhoodName': 'بنی هاشم', 'Areaid': 4}, 72: {'id': 72, 'NeighborhoodName': 'نیرودریایی', 'Areaid': 4}, 89: {'id': 89, 'NeighborhoodName': 'اجاره دار', 'Areaid': 7}, 90: {'id': 90, 'NeighborhoodName': 'ارامنه', 'Areaid': 7}, 91: {'id': 91, 'NeighborhoodName': 'امجدیه', 'Areaid': 7}, 92: {'id': 92, 'NeighborhoodName': 'سهروردی', 'Areaid': 7}, 93: {'id': 93, 'NeighborhoodName': 'بهار', 'Areaid': 7}, 94: {'id': 94, 'NeighborhoodName': 'حشمتیه', 'Areaid': 7}, 95: {'id': 95, 'NeighborhoodName': 'سبلان', 'Areaid': 8}, 96: {'id': 96, 'NeighborhoodName': 'اندیشه', 'Areaid': 7}, 97: {'id': 97, 'NeighborhoodName': 'قصر', 'Areaid': 7}, 98: {'id': 98, 'NeighborhoodName': 'کاج', 'Areaid': 7}, 99: {'id': 99, 'NeighborhoodName': 'نظام اباد', 'Areaid': 8}, 100: {'id': 100, 'NeighborhoodName': 'نیلوفر', 'Areaid': 7}, 101: {'id': 101, 'NeighborhoodName': 'هفت تیر', 'Areaid': 7}, 102: {'id': 102, 'NeighborhoodName': 'نامجو', 'Areaid': 7}, 103: {'id': 103, 'NeighborhoodName': 'تهران نو', 'Areaid': 13}, 105: {'id': 105, 'NeighborhoodName': 'مجیدیه جنوبی', 'Areaid': 8}, 106: {'id': 106, 'NeighborhoodName': 'نارمک غربی', 'Areaid': 8}, 107: {'id': 107, 'NeighborhoodName': 'وحیدیه', 'Areaid': 8}, 108: {'id': 108, 'NeighborhoodName': 'یوسف آباد', 'Areaid': 6}, 109: {'id': 109, 'NeighborhoodName': 'ایرانشهر', 'Areaid': 6}, 110: {'id': 110, 'NeighborhoodName': 'گلبرگ غربی', 'Areaid': 8}, 111: {'id': 111, 'NeighborhoodName': 'گاندی', 'Areaid': 3}, 112: {'id': 112, 'NeighborhoodName': 'ساعی', 'Areaid': 6}, 113: {'id': 113, 'NeighborhoodName': 'طالقانی', 'Areaid': 6}, 114: {'id': 114, 'NeighborhoodName': 'سناعی', 'Areaid': 6}, 115: {'id': 115, 'NeighborhoodName': 'گلها', 'Areaid': 6}, 116: {'id': 116, 'NeighborhoodName': 'توانیر', 'Areaid': 6}, 117: {'id': 117, 'NeighborhoodName': 'فاطمی', 'Areaid': 6}, 118: {'id': 118, 'NeighborhoodName': 'مطهری', 'Areaid': 7}, 119: {'id': 119, 'NeighborhoodName': 'بهشتی', 'Areaid': 7}, 120: {'id': 120, 'NeighborhoodName': 'کردستان', 'Areaid': 6}, 121: {'id': 121, 'NeighborhoodName': 'دردشت', 'Areaid': 8}, 133: {'id': 133, 'NeighborhoodName': 'اکباتان', 'Areaid': 5}, 134: {'id': 134, 'NeighborhoodName': 'ستاری', 'Areaid': 5}, 135: {'id': 135, 'NeighborhoodName': 'شهران جنوبی', 'Areaid': 5}, 136: {'id': 136, 'NeighborhoodName': 'پیامبر', 'Areaid': 5}, 137: {'id': 137, 'NeighborhoodName': 'جنت آباد', 'Areaid': 5}, 138: {'id': 138, 'NeighborhoodName': 'باغ فیض', 'Areaid': 5}, 139: {'id': 139, 'NeighborhoodName': 'شهران شمالی', 'Areaid': 5}, 140: {'id': 140, 'NeighborhoodName': 'آیت الله کاشانی', 'Areaid': 5}, 141: {'id': 141, 'NeighborhoodName': 'پونک', 'Areaid': 5}, 142: {'id': 142, 'NeighborhoodName': 'نیروی هوایی', 'Areaid': 13}, 143: {'id': 143, 'NeighborhoodName': 'جردن', 'Areaid': 3}, 144: {'id': 144, 'NeighborhoodName': 'ولیعصر', 'Areaid': 1}, 145: {'id': 145, 'NeighborhoodName': 'انقلاب', 'Areaid': 6}, 146: {'id': 146, 'NeighborhoodName': 'پیروزی', 'Areaid': 14}, 147: {'id': 147, 'NeighborhoodName': 'افسریه', 'Areaid': 15}, 149: {'id': 149, 'NeighborhoodName': 'قاسم آباد', 'Areaid': 4}, 150: {'id': 150, 'NeighborhoodName': 'شهر زیبا', 'Areaid': 5}, 151: {'id': 151, 'NeighborhoodName': 'تهرانسر', 'Areaid': 21}, 152: {'id': 152, 'NeighborhoodName': 'اوقاف', 'Areaid': 4}, 153: {'id': 153, 'NeighborhoodName': 'فردوس', 'Areaid': 5}, 154: {'id': 154, 'NeighborhoodName': 'سپهر', 'Areaid': 2}, 155: {'id': 155, 'NeighborhoodName': 'سازمان برنامه', 'Areaid': 5}, 156: {'id': 156, 'NeighborhoodName': 'سبلان جنوبی', 'Areaid': 8}, 157: {'id': 157, 'NeighborhoodName': 'سبلان شمالی', 'Areaid': 8}, 158: {'id': 158, 'NeighborhoodName': 'سوهانک', 'Areaid': 1}, 159: {'id': 159, 'NeighborhoodName': 'سعادت آباد', 'Areaid': 2}, 160: {'id': 160, 'NeighborhoodName': 'دارآباد', 'Areaid': 1}, 161: {'id': 161, 'NeighborhoodName': 'اندرزگو', 'Areaid': 1}, 162: {'id': 162, 'NeighborhoodName': 'عباس آباد', 'Areaid': 7}, 163: {'id': 163, 'NeighborhoodName': 'جمشیدیه', 'Areaid': 1}, 164: {'id': 164, 'NeighborhoodName': 'ابوذر جنوبی', 'Areaid': 14}, 166: {'id': 166, 'NeighborhoodName': 'گلاب دره', 'Areaid': 1}, 169: {'id': 169, 'NeighborhoodName': 'پرستار', 'Areaid': 14}, 170: {'id': 170, 'NeighborhoodName': 'خاک سفید', 'Areaid': 4}, 171: {'id': 171, 'NeighborhoodName': 'دهم فروردین', 'Areaid': 14}, 172: {'id': 172, 'NeighborhoodName': 'محلاتی', 'Areaid': 14}, 173: {'id': 173, 'NeighborhoodName': 'بلوار ابوذر', 'Areaid': 14}, 174: {'id': 174, 'NeighborhoodName': 'مجید آباد', 'Areaid': 4}, 175: {'id': 175, 'NeighborhoodName': 'جیحون', 'Areaid': 4}, 176: {'id': 176, 'NeighborhoodName': 'ارتش', 'Areaid': 1}, 177: {'id': 177, 'NeighborhoodName': 'آرژانتین', 'Areaid': 7}, 178: {'id': 178, 'NeighborhoodName': 'دزاشیب', 'Areaid': 1}, 179: {'id': 179, 'NeighborhoodName': 'مسعودیه', 'Areaid': 15}}
transaction_ch = {1: {'id': 1, 'name': 'فروش'}, 2: {'id': 2, 'name': 'رهن و اجاره'}, 3: {'id': 3, 'name': 'رهن'}, 4: {'id': 4, 'name': 'مشارکت'}, 5: {'id': 5, 'name': 'معاوضه'}}
property_type_ch = {1: {'id': 1, 'name': 'آپارتمان'}, 2: {'id': 2, 'name': 'ویلا'}, 3: {'id': 3, 'name': 'کلنگی'}, 4: {'id': 4, 'name': 'دفتر کار'}, 5: {'id': 5, 'name': 'سوئیت'}, 6: {'id': 6, 'name': 'مغازه'}, 7: {'id': 7, 'name': 'مستغلات'}}
# floor_number_ch = {108: {'id': 108, 'FloorName': 'درکل', 'Valnumber': 102}, 107: {'id': 107, 'FloorName': 'مختلف', 'Valnumber': 101}, 1: {'id': 1, 'FloorName': 'زیرزمین', 'Valnumber': -2}, 2: {'id': 2, 'FloorName': 'همکف', 'Valnumber': 0}, 3: {'id': 3, 'FloorName': 'زیرهمکف', 'Valnumber': -1}, 4: {'id': 4, 'FloorName': 'طبقه1', 'Valnumber': 1}, 5: {'id': 5, 'FloorName': 'طبقه2', 'Valnumber': 2}, 7: {'id': 7, 'FloorName': 'طبقه3', 'Valnumber': 3}, 8: {'id': 8, 'FloorName': 'طبقه4', 'Valnumber': 4}, 9: {'id': 9, 'FloorName': 'طبقه5', 'Valnumber': 5}, 10: {'id': 10, 'FloorName': 'طبقه6', 'Valnumber': 6}, 11: {'id': 11, 'FloorName': 'طبقه7', 'Valnumber': 7}, 12: {'id': 12, 'FloorName': 'طبقه8', 'Valnumber': 8}, 13: {'id': 13, 'FloorName': 'طبقه9', 'Valnumber': 9}, 14: {'id': 14, 'FloorName': 'طبقه10', 'Valnumber': 10}, 15: {'id': 15, 'FloorName': 'طبقه11', 'Valnumber': 11}, 16: {'id': 16, 'FloorName': 'طبقه12', 'Valnumber': 12}, 17: {'id': 17, 'FloorName': 'طبقه13', 'Valnumber': 13}, 18: {'id': 18, 'FloorName': 'طبقه14', 'Valnumber': 14}, 19: {'id': 19, 'FloorName': 'طبقه15', 'Valnumber': 15}, 20: {'id': 20, 'FloorName': 'طبقه16', 'Valnumber': 16}, 21: {'id': 21, 'FloorName': 'طبقه17', 'Valnumber': 17}, 22: {'id': 22, 'FloorName': 'طبقه18', 'Valnumber': 18}, 23: {'id': 23, 'FloorName': 'طبقه19', 'Valnumber': 19}, 24: {'id': 24, 'FloorName': 'طبقه20', 'Valnumber': 20}, 25: {'id': 25, 'FloorName': 'طبقه21', 'Valnumber': 21}, 26: {'id': 26, 'FloorName': 'طبقه22', 'Valnumber': 22}, 27: {'id': 27, 'FloorName': 'طبقه23', 'Valnumber': 23}, 28: {'id': 28, 'FloorName': 'طبقه24', 'Valnumber': 24}, 29: {'id': 29, 'FloorName': 'طبقه25', 'Valnumber': 25}, 30: {'id': 30, 'FloorName': 'طبقه26', 'Valnumber': 26}, 31: {'id': 31, 'FloorName': 'طبقه27', 'Valnumber': 27}, 32: {'id': 32, 'FloorName': 'طبقه28', 'Valnumber': 28}, 33: {'id': 33, 'FloorName': 'طبقه29', 'Valnumber': 29}, 34: {'id': 34, 'FloorName': 'طبقه30', 'Valnumber': 30}, 35: {'id': 35, 'FloorName': 'طبقه31', 'Valnumber': 31}, 36: {'id': 36, 'FloorName': 'طبقه32', 'Valnumber': 32}, 37: {'id': 37, 'FloorName': 'طبقه33', 'Valnumber': 33}, 38: {'id': 38, 'FloorName': 'طبقه34', 'Valnumber': 34}, 39: {'id': 39, 'FloorName': 'طبقه35', 'Valnumber': 35}, 40: {'id': 40, 'FloorName': 'طبقه36', 'Valnumber': 36}, 41: {'id': 41, 'FloorName': 'طبقه37', 'Valnumber': 37}, 42: {'id': 42, 'FloorName': 'طبقه38', 'Valnumber': 38}, 43: {'id': 43, 'FloorName': 'طبقه39', 'Valnumber': 39}, 44: {'id': 44, 'FloorName': 'طبقه40', 'Valnumber': 40}, 45: {'id': 45, 'FloorName': 'طبقه41', 'Valnumber': 41}, 46: {'id': 46, 'FloorName': 'طبقه42', 'Valnumber': 42}, 47: {'id': 47, 'FloorName': 'طبقه43', 'Valnumber': 43}, 48: {'id': 48, 'FloorName': 'طبقه44', 'Valnumber': 44}, 49: {'id': 49, 'FloorName': 'طبقه45', 'Valnumber': 45}, 50: {'id': 50, 'FloorName': 'طبقه46', 'Valnumber': 46}, 51: {'id': 51, 'FloorName': 'طبقه47', 'Valnumber': 47}, 52: {'id': 52, 'FloorName': 'طبقه48', 'Valnumber': 48}, 53: {'id': 53, 'FloorName': 'طبقه49', 'Valnumber': 49}, 54: {'id': 54, 'FloorName': 'طبقه50', 'Valnumber': 50}, 55: {'id': 55, 'FloorName': 'طبقه51', 'Valnumber': 51}, 56: {'id': 56, 'FloorName': 'طبقه52', 'Valnumber': 52}, 57: {'id': 57, 'FloorName': 'طبقه53', 'Valnumber': 53}, 58: {'id': 58, 'FloorName': 'طبقه54', 'Valnumber': 54}, 59: {'id': 59, 'FloorName': 'طبقه55', 'Valnumber': 55}, 60: {'id': 60, 'FloorName': 'طبقه56', 'Valnumber': 56}, 61: {'id': 61, 'FloorName': 'طبقه57', 'Valnumber': 57}, 62: {'id': 62, 'FloorName': 'طبقه58', 'Valnumber': 58}, 63: {'id': 63, 'FloorName': 'طبقه59', 'Valnumber': 59}, 64: {'id': 64, 'FloorName': 'طبقه60', 'Valnumber': 60}, 65: {'id': 65, 'FloorName': 'طبقه61', 'Valnumber': 61}, 66: {'id': 66, 'FloorName': 'طبقه62', 'Valnumber': 62}, 67: {'id': 67, 'FloorName': 'طبقه63', 'Valnumber': 63}, 68: {'id': 68, 'FloorName': 'طبقه64', 'Valnumber': 64}, 69: {'id': 69, 'FloorName': 'طبقه65', 'Valnumber': 65}, 70: {'id': 70, 'FloorName': 'طبقه66', 'Valnumber': 66}, 71: {'id': 71, 'FloorName': 'طبقه67', 'Valnumber': 67}, 72: {'id': 72, 'FloorName': 'طبقه68', 'Valnumber': 68}, 73: {'id': 73, 'FloorName': 'طبقه69', 'Valnumber': 69}, 74: {'id': 74, 'FloorName': 'طبقه70', 'Valnumber': 70}, 75: {'id': 75, 'FloorName': 'طبقه71', 'Valnumber': 71}, 76: {'id': 76, 'FloorName': 'طبقه72', 'Valnumber': 72}, 77: {'id': 77, 'FloorName': 'طبقه73', 'Valnumber': 73}, 78: {'id': 78, 'FloorName': 'طبقه74', 'Valnumber': 74}, 79: {'id': 79, 'FloorName': 'طبقه75', 'Valnumber': 75}, 80: {'id': 80, 'FloorName': 'طبقه76', 'Valnumber': 76}, 81: {'id': 81, 'FloorName': 'طبقه77', 'Valnumber': 77}, 82: {'id': 82, 'FloorName': 'طبقه78', 'Valnumber': 78}, 83: {'id': 83, 'FloorName': 'طبقه79', 'Valnumber': 79}, 84: {'id': 84, 'FloorName': 'طبقه80', 'Valnumber': 80}, 85: {'id': 85, 'FloorName': 'طبقه81', 'Valnumber': 81}, 86: {'id': 86, 'FloorName': 'طبقه82', 'Valnumber': 82}, 87: {'id': 87, 'FloorName': 'طبقه83', 'Valnumber': 83}, 88: {'id': 88, 'FloorName': 'طبقه84', 'Valnumber': 84}, 89: {'id': 89, 'FloorName': 'طبقه85', 'Valnumber': 85}, 90: {'id': 90, 'FloorName': 'طبقه86', 'Valnumber': 86}, 91: {'id': 91, 'FloorName': 'طبقه87', 'Valnumber': 87}, 92: {'id': 92, 'FloorName': 'طبقه88', 'Valnumber': 88}, 93: {'id': 93, 'FloorName': 'طبقه89', 'Valnumber': 89}, 94: {'id': 94, 'FloorName': 'طبقه90', 'Valnumber': 90}, 95: {'id': 95, 'FloorName': 'طبقه91', 'Valnumber': 91}, 96: {'id': 96, 'FloorName': 'طبقه92', 'Valnumber': 92}, 97: {'id': 97, 'FloorName': 'طبقه93', 'Valnumber': 93}, 98: {'id': 98, 'FloorName': 'طبقه94', 'Valnumber': 94}, 99: {'id': 99, 'FloorName': 'طبقه95', 'Valnumber': 95}, 100: {'id': 100, 'FloorName': 'طبقه96', 'Valnumber': 96}, 101: {'id': 101, 'FloorName': 'طبقه97', 'Valnumber': 97}, 102: {'id': 102, 'FloorName': 'طبقه98', 'Valnumber': 98}, 103: {'id': 103, 'FloorName': 'طبقه99', 'Valnumber': 99}, 104: {'id': 104, 'FloorName': 'طبقه100', 'Valnumber': 100}}
sleep_numbers_ch = {0: {'id': 0, 'Numberofsleeps': 'ندارد'}, 1: {'id': 1, 'Numberofsleeps': 'یک خواب'}, 2: {'id': 2, 'Numberofsleeps': 'دو خواب'}, 3: {'id': 3, 'Numberofsleeps': 'سه خواب'}, 4: {'id': 4, 'Numberofsleeps': 'چهار خواب'}, 5: {'id': 5, 'Numberofsleeps': 'پنج خواب'}, 6: {'id': 6, 'Numberofsleeps': 'شش خواب'}, 7: {'id': 7, 'Numberofsleeps': 'هفت خواب'}, 8: {'id': 8, 'Numberofsleeps': 'هشت خواب'}, 9: {'id': 9, 'Numberofsleeps': 'نه خواب'}, 10: {'id': 10, 'Numberofsleeps': 'ده خواب'}}
kitchen_ch = {16: {'id': 16, 'name': 'MDF'}, 17: {'id': 17, 'name': 'فرنیش'}, 18: {'id': 18, 'name': 'فلزی'}, 19: {'id': 19, 'name': 'های گلاس'}, 20: {'id': 20, 'name': 'فورمات'}, 21: {'id': 21, 'name': 'چوبی فلزی'}, 22: {'id': 22, 'name': 'فلزطرح چوب'}, 23: {'id': 23, 'name': 'چوبی'}, 24: {'id': 24, 'name': 'چوبی خارجی'}, 25: {'id': 25, 'name': 'گازر'}, 26: {'id': 26, 'name': 'نف آلمان'}, 27: {'id': 27, 'name': 'مبله'}, 28: {'id': 28, 'name': 'نیمه مبله'}, 29: {'id': 29, 'name': 'فایبرگلاس'}, 30: {'id': 30, 'name': 'آبدارخانه'}, 31: {'id': 31, 'name': 'مشترک'}, 32: {'id': 32, 'name': 'دلخواه'}, 33: {'id': 33, 'name': 'ماج نما'}, 34: {'id': 34, 'name': 'HDF'}, 35: {'id': 35, 'name': 'PVC'}, 36: {'id': 36, 'name': 'پلی استر'}, 37: {'id': 37, 'name': 'گالوانیزه'}, 38: {'id': 38, 'name': 'ممبران'}, 39: {'id': 39, 'name': 'جزیره ای'}, 40: {'id': 40, 'name': 'ندارد'}, 41: {'id': 41, 'name': 'نامشخص'}}
telephone_line_ch = {1: {'id': 1, 'Linestatus': 'ندارد'}, 2: {'id': 2, 'Linestatus': '1 خط'}, 3: {'id': 3, 'Linestatus': '2 خط'}, 4: {'id': 4, 'Linestatus': '3 خط'}, 5: {'id': 5, 'Linestatus': 'سانترال'}}
wc_ch = {1: {'id': 1, 'name': 'ایرانی'}, 2: {'id': 2, 'name': 'ایرانی و فرنگی'}, 3: {'id': 3, 'name': 'در حیاط'}, 4: {'id': 4, 'name': 'فرنگی'}, 5: {'id': 5, 'name': 'مشترک'}, 6: {'id': 6, 'name': 'ندارد'}}
floor_type_ch = {1: {'id': 1, 'name': 'سرامیک'}, 2: {'id': 2, 'name': 'موزایک'}, 3: {'id': 3, 'name': 'پارکت'}, 4: {'id': 4, 'name': 'سنگ'}, 5: {'id': 5, 'name': 'سیمان'}, 6: {'id': 6, 'name': 'کف پوش'}, 7: {'id': 7, 'name': 'گرانیت'}, 8: {'id': 8, 'name': 'لمینت'}, 9: {'id': 9, 'name': 'متنوع'}, 10: {'id': 10, 'name': 'موکت'}, 11: {'id': 11, 'name': 'نا مشخص'}}
view_type_ch = {1: {'id': 1, 'name': 'نا مشخص', 'Typeoffacade': 'نا مشخص'}, 3: {'id': 3, 'name': 'PVC', 'Typeoffacade': 'PVC'}, 4: {'id': 4, 'name': 'آجر', 'Typeoffacade': 'آجر'}, 5: {'id': 5, 'name': 'آجر سه سانت', 'Typeoffacade': 'آجر سه سانت'}, 6: {'id': 6, 'name': 'آلومینیوم', 'Typeoffacade': 'آلومینیوم'}, 7: {'id': 7, 'name': 'آلومینیوم شیشه', 'Typeoffacade': 'آلومینیوم شیشه'}, 8: {'id': 8, 'name': 'اسپانیش', 'Typeoffacade': 'اسپانیش'}, 9: {'id': 9, 'name': 'انگلیسی', 'Typeoffacade': 'انگلیسی'}, 10: {'id': 10, 'name': 'بتنی', 'Typeoffacade': 'بتنی'}, 11: {'id': 11, 'name': 'تراورتن', 'Typeoffacade': 'تراورتن'}, 12: {'id': 12, 'name': 'رفلکس', 'Typeoffacade': 'رفلکس'}, 13: {'id': 13, 'name': 'رومی', 'Typeoffacade': 'رومی'}, 14: {'id': 14, 'name': 'رومی شیشه', 'Typeoffacade': 'رومی شیشه'}, 15: {'id': 15, 'name': 'سرامیک', 'Typeoffacade': 'سرامیک'}, 16: {'id': 16, 'name': 'سرامیک و شیشه', 'Typeoffacade': 'سرامیک و شیشه'}, 17: {'id': 17, 'name': 'سنگ', 'Typeoffacade': 'سنگ'}, 18: {'id': 18, 'name': 'سنگ رومی', 'Typeoffacade': 'سنگ رومی'}, 19: {'id': 19, 'name': 'سنگ سیمان', 'Typeoffacade': 'سنگ سیمان'}, 20: {'id': 20, 'name': 'سنگ و شیشه', 'Typeoffacade': 'سنگ و شیشه'}, 21: {'id': 21, 'name': 'شیشه', 'Typeoffacade': 'شیشه'}, 22: {'id': 22, 'name': 'گرانیت', 'Typeoffacade': 'گرانیت'}, 23: {'id': 23, 'name': 'گرانیت شیشه', 'Typeoffacade': 'گرانیت شیشه'}, 24: {'id': 24, 'name': 'کلاسیک', 'Typeoffacade': 'کلاسیک'}, 25: {'id': 25, 'name': 'کنیتکس', 'Typeoffacade': 'کنیتکس'}, 26: {'id': 26, 'name': 'کامپوزیت', 'Typeoffacade': 'کامپوزیت'}, 27: {'id': 27, 'name': 'کنیتکس رومی', 'Typeoffacade': 'کنیتکس رومی'}, 28: {'id': 28, 'name': 'سیمان', 'Typeoffacade': 'سیمان'}, 29: {'id': 29, 'name': 'ترکیبی', 'Typeoffacade': 'ترکیبی'}, 33: {'id': 33, 'name': 'کرکره برقی', 'Typeoffacade': 'کرکره برقی'}, 34: {'id': 34, 'name': 'چوبی', 'Typeoffacade': 'چوبی'}}
document_type_ch = {1: {'id': 1, 'name': 'نامشخص'}, 2: {'id': 2, 'name': 'اوقافی'}, 3: {'id': 3, 'name': 'بنیادی'}, 4: {'id': 4, 'name': 'تعاونی'}, 5: {'id': 5, 'name': 'زمین شهری'}, 6: {'id': 6, 'name': 'شخصی'}, 7: {'id': 7, 'name': 'فرمان امام'}, 8: {'id': 8, 'name': 'اداری'}, 9: {'id': 9, 'name': 'مسکونی'}, 10: {'id': 10, 'name': 'تجاری'}, 12: {'id': 12, 'name': 'قولنامه ای'}, 13: {'id': 13, 'name': 'سند مادر'}, 16: {'id': 16, 'name': 'توسعه لویزان'}, 17: {'id': 17, 'name': 'تک برگ'}, 18: {'id': 18, 'name': 'منگوله\u200cدار'}, 19: {'id': 19, 'name': 'سایر'}}
job_ch = {5: {'id': 5, 'name': 'مشاور'}, 6: {'id': 6, 'name': 'منشی'}, 7: {'id': 7, 'name': 'مدیر'}, 8: {'id': 8, 'name': 'آبدارچی'}}
# building_age_ch = {1: {'id': 1, 'name': 'نوساز  تا 5 سال', 'minimum': 0, 'maximum': 5}, 2: {'id': 2, 'name': '5 تا 10 سال', 'minimum': 5, 'maximum': 10}, 3: {'id': 3, 'name': '10 تا 15 سال', 'minimum': 10, 'maximum': 15}, 4: {'id': 4, 'name': '15 تا 20 سال', 'minimum': 15, 'maximum': 20}, 5: {'id': 5, 'name': '20 تا 30 سال', 'minimum': 20, 'maximum': 30}, 6: {'id': 6, 'name': ' بالای 30 سال', 'minimum': 30, 'maximum': 120}}
features_ch = {1: {'id': 1, 'name': 'elevator', 'persianname': 'آسانسور', 'type': 2}, 2: {'id': 2, 'name': 'open', 'persianname': 'open', 'type': 1}, 3: {'id': 3, 'name': 'parking', 'persianname': 'پارکینگ', 'type': 2}, 4: {'id': 4, 'name': 'warehouse', 'persianname': 'انباری', 'type': 2}, 5: {'id': 5, 'name': 'cooler', 'persianname': 'کولر', 'type': 3}, 6: {'id': 6, 'name': 'gas', 'persianname': 'گاز', 'type': 3}, 7: {'id': 7, 'name': 'radiator', 'persianname': 'شوفاژ', 'type': 3}, 8: {'id': 8, 'name': 'package', 'persianname': 'پکیج', 'type': 3}, 9: {'id': 9, 'name': 'ductsplit', 'persianname': 'داکت اسپلیت', 'type': 3}, 10: {'id': 10, 'name': 'gascooler', 'persianname': 'کولر گازی', 'type': 3}, 11: {'id': 11, 'name': 'chiller', 'persianname': 'چیلر', 'type': 3}, 12: {'id': 12, 'name': 'balcony', 'persianname': 'بالکن', 'type': 2}, 13: {'id': 13, 'name': 'iphonevideo', 'persianname': 'آیفون تصویری', 'type': 1}, 14: {'id': 14, 'name': 'remotedoor', 'persianname': 'درب ریموت', 'type': 1}, 15: {'id': 15, 'name': 'patio', 'persianname': 'پاسیو', 'type': 1}, 16: {'id': 16, 'name': 'fancoil', 'persianname': 'فن کوئل', 'type': 3}, 17: {'id': 17, 'name': 'quicksale', 'persianname': 'فروش فوری', 'type': 1}, 18: {'id': 18, 'name': 'backyard', 'persianname': 'حیاط خلوت', 'type': 1}, 19: {'id': 19, 'name': 'yard', 'persianname': 'حیاط', 'type': 1}, 20: {'id': 20, 'name': 'underground', 'persianname': 'زیرزمین', 'type': 1}, 21: {'id': 21, 'name': 'flat', 'persianname': 'فلت', 'type': 1}, 22: {'id': 22, 'name': 'heatfromthefloor', 'persianname': 'حرارت از کف', 'type': 3}, 23: {'id': 23, 'name': 'fireplace', 'persianname': 'شومینه', 'type': 1}, 24: {'id': 24, 'name': 'mrroman', 'persianname': 'مسترروم', 'type': 1}, 25: {'id': 25, 'name': 'swimmingpool', 'persianname': 'استخر', 'type': 2}, 26: {'id': 26, 'name': 'sauna', 'persianname': 'سونا', 'type': 2}, 27: {'id': 27, 'name': 'jacuzzi', 'persianname': 'جکوزی', 'type': 2}, 28: {'id': 28, 'name': 'residential', 'persianname': 'مسکونی', 'type': 1}, 29: {'id': 29, 'name': 'Discharge', 'persianname': 'تخلیه', 'type': 1}, 30: {'id': 30, 'name': 'rent', 'persianname': 'اجاره', 'type': 1}, 31: {'id': 31, 'name': 'reconstructed', 'persianname': 'بازسازی شده', 'type': 1}, 32: {'id': 32, 'name': 'rightofbusiness', 'persianname': 'سرقفلی', 'type': 1}, 33: {'id': 33, 'name': 'property', 'persianname': 'ملکیت', 'type': 1}, 34: {'id': 34, 'name': 'roofgarden', 'persianname': 'روف گاردن', 'type': 1}, 35: {'id': 35, 'name': 'convertable', 'persianname': 'قابل تبدیل', 'type': 1}, 36: {'id': 36, 'name': 'unlocked', 'persianname': 'کلید نخورده', 'type': 1}, 37: {'id': 37, 'name': 'desktopgas', 'persianname': 'گاز رومیزی', 'type': 1}, 38: {'id': 38, 'name': 'habitable', 'persianname': 'قابل سکونت', 'type': 1}, 39: {'id': 39, 'name': 'barbecue', 'persianname': 'باربیکیو', 'type': 1}, 40: {'id': 40, 'name': 'air conditioner', 'persianname': 'هواساز', 'type': 1}, 41: {'id': 41, 'name': 'furnished', 'persianname': 'مبله', 'type': 1}, 42: {'id': 42, 'name': 'salone', 'persianname': 'سالن اجتماعات', 'type': 1}, 43: {'id': 43, 'name': 'gym hall', 'persianname': 'سالن جیم', 'type': 1}, 44: {'id': 44, 'name': 'fire extinguishing', 'persianname': 'اطفا حریق', 'type': 1}, 45: {'id': 45, 'name': 'CCTV', 'persianname': 'دوربین مدار بسته', 'type': 1}, 46: {'id': 46, 'name': 'lobby', 'persianname': 'لابی', 'type': 1}, 47: {'id': 47, 'name': 'the janitor', 'persianname': 'سرایدار', 'type': 1}, 48: {'id': 48, 'name': 'Central vacuum cleaner', 'persianname': 'جاروبرقی مرکزی', 'type': 1}}
# don't use this for representation like: PostMongoSerializer(DictToObject(post_col)).data
# in updating must be like: PostMongoSerializer(pk=1, data=data, partial=True, request=request)
# in creation: PostMongoSerializer(data=data, prequest=request)
class FileMongoSerializer(MongoSerializer):
    presents = [('1', _('new')), ('2', _('open')), ('3', _('hot'))]
    # [title, description, request.user/author required
    file_id = serializers.CharField(read_only=True, validators=[MongoUniqueValidator(mongo_db.file, 'file_id')])
    title = serializers.CharField(validators=[MongoUniqueValidator(mongo_db.file, 'title')], max_length=255)
    slug = serializers.SlugField(allow_unicode=True, required=False)    # slug generates from title (in to_internal_value)
    published_date = TimestampField(auto_now_add=True, jalali=True, required=False)
    updated = TimestampField(auto_now=True, jalali=True, required=False)
    meta_title = serializers.CharField(allow_blank=True, max_length=60, required=False, default='')
    meta_description = serializers.CharField(allow_blank=True, required=False, validators=[MaxLengthValidator(160)])
    description = serializers.CharField(validators=[MaxLengthValidator(1000)])
    metraj = serializers.CharField(max_length=50, required=False)
    total_price = DecimalFile(max_length=50, default='0')  # price in first can contain strings like 'toman...'
    price_per_meter = DecimalFile(max_length=50, default='0')
    age = serializers.CharField(required=False)  # in divar crawling all data is string (and raise error in to_internal)
    floor_number = serializers.CharField(required=False, allow_null=True)  # could be None (vilaii) or long string
    specs = serializers.JSONField(required=False)    # additional information like: {'jahat': 'jonobi', ..}
    source = serializers.CharField(max_length=255, required=False)  # like: 'https://divar.ir'
    presentation_status = serializers.ChoiceField(choices=presents, default='1')
    visible = serializers.BooleanField(default=True)

    neighborhoods = serializers.JSONField(required=False)   # receive id (integer or str), returns dict from 'field_ch'
    transaction = serializers.JSONField(required=False)
    property_type = serializers.JSONField(required=False)
    sleep_numbers = serializers.JSONField(required=False)
    kitchen = serializers.JSONField(required=False)
    telephone_line = serializers.JSONField(required=False)
    wc = serializers.JSONField(required=False)
    floor_type = serializers.JSONField(required=False)
    view_type = serializers.JSONField(required=False)
    document_type = serializers.JSONField(required=False)
    job = serializers.JSONField(required=False)
    features = serializers.ListSerializer(child=serializers.CharField(max_length=100, required=False), required=False)

    icon = OneToMultipleImageMongo(sizes=['240', '420', '640', '720', '960', '1280', 'default'], upload_to='file_images/icons/', required=False)
    images = ImageSerializer(many=True, upload_to='file_images/', required=False)
    comments = CommentSerializer(many=True, required=False)
    author = UserNameSerializer(required=False)  # author can fill auto in to_internal_value, otherwise must input
    category = CategorySerializer(required=False, read_only=True)  # it's validated_data fill in 'to_internal_value'

    class Meta:
        model = mongo_db.file
        list_serializer_class = FileListMongoSerializer

    @property
    def context(self):
        return self._context

    @context.setter
    def context(self, value):      # default .context have no setter so should define manually
        self._context = value

    def to_internal_value(self, data):
        if not data.get('slug') and data.get('title'):
            data['slug'] = slugify(data['title'], allow_unicode=True)  # data==request.data==self.initial_data mutable
        internal_value = super().to_internal_value(data)

        request, change = self.context.get('request'), self.context.get('change', False)
        if not change:
            internal_value['file_id'] = uuid.uuid4().hex[:6]       # generate 7 digit character

        if data.get('category'):
            level = Category.objects.filter(id=data['category']).values_list('level', flat=True)[0]
            related = 'father_category'
            # '__father_category' * -1 == '', prefetch_related('child_categories') don't need because of single category
            i = Category._meta.get_field('level').validators[1].limit_value-1-level  # raise error when use directly!
            related += '__father_category' * i
            cat = Category.objects.filter(id=data['category']).select_related(related)[0]
            internal_value['category'] = cat
        if not change:
            # if provide author id in request.data, 'internal_value' contain user.
            if not internal_value.get('author') and request and request.user.is_authenticated:
                internal_value['author'] = request.user
            else:
                # note, if internal_value==None, 'def validate_author' will not call
                raise ValidationError({"author": "user not provided. login, pass 'request' parameter or add user id manually"})
        return internal_value

    # 'def validate' not run sometimes because of partial=True
    def validate_metraj(self, value):
        if value.isdigit():    # even for persian numbers .isdigit  works
            return str(int(value))     # convert to en
        else:
            raise ValidationError(f"'metraj' has not valid type: ({value})")

    def validate_total_price(self, value):
        if value.isdigit():    # even for persian numbers .isdigit and Decimal() works
            return Decimal(value)
        else:
            try:
                pr_price = value.replace('تومان', '').replace('٬', '').replace(' ', '')
                return Decimal(pr_price)
            except:
                raise ValidationError(f"'total_price' has not valid value: ({value})")

    def validate_price_per_meter(self, value):
        if value.isdigit():
            return Decimal(value)
        else:
            try:
                pr_price = value.replace('تومان', '').replace('٬', '').replace(' ', '')
                return Decimal(pr_price)
            except:
                raise ValidationError(f"'price_per_meter' has not valid value: ({value})")

    def validate_age(self, value):
        try:
            return str(int(value))          # convert pr number to en
        except:
            return value             # value could be like: 'qabl az 1370' but still should be save

    def validate_floor_number(self, value):    # could be string like: '5 az 6' or '5 az hamkaf' ...
        if isinstance(value, int):
            return value
        else:
            try:
                result = re.findall(r'\d+', value)   # take first sequence of number
                if result:
                    return str(int(result[0]))
                else:
                    raise
            except:
                raise ValidationError(f"'floor_number' has not valid value: ({value})")

    def validate_neighborhoods(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return neighborhoods_ch.get(value)
        else:
            return value           # value was sent from external api (like divar)

    def validate_transaction(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return transaction_ch.get(value)
        else:
            return value

    def validate_property_type(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return property_type_ch.get(int(value))
        else:
            return value

    def validate_sleep_numbers(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return sleep_numbers_ch.get(int(value))
        else:
            return value

    def validate_kitchen(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return kitchen_ch.get(int(value))
        else:
            return value

    def validate_telephone_line(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return telephone_line_ch.get(int(value))
        else:
            return value

    def validate_wc(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return wc_ch.get(int(value))
        else:
            return value

    def validate_floor_type(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return floor_type_ch.get(int(value))
        else:
            return value

    def validate_view_type(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return view_type_ch.get(int(value))
        else:
            return value

    def validate_document_type(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return document_type_ch.get(int(value))
        else:
            return value

    def validate_job(self, value):    # receive id and returns dict data
        if isinstance(value, int):
            return job_ch.get(int(value))
        else:
            return value

    def validate_features(self, value):    # receive list of features
        if isinstance(value, list):
            # value is list of features like: ['parking', 'asansor\u200c',..], came from crawler or API.
            if isinstance(value[0], int) or value[0].isdigit():
                raise "provide list of features like: ['parking', 'asansor',..]"
            return value
        else:
            raise "provide list of features"


class Bserializer(serializers.Serializer):
    def is_valid(self, raise_exception=False):
        ret = super().is_valid(raise_exception=raise_exception)
        return ret


class ImageSerializer2(Bserializer):
    # image can be url too (like: 'http:....')
    name = serializers.CharField(max_length=100, required=False)
    image = serializers.CharField(allow_null=True, required=False)  # image can be url('http..')|Base64|python open
    alt = serializers.CharField(max_length=100, allow_blank=True, default='')

class Field1(serializers.CharField):
    def to_internal_value(self, data):
        return data
class S1(serializers.Serializer):
    f1 = Field1(required=False)


class TestSerializer(serializers.Serializer):
    title = serializers.IntegerField()
    #s1 = S1(required=False)

    def validate_title(self, value):
        try:
            raise
        except:
            raise ValidationError('asdasd')
        return Decimal(value)




