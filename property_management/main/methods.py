from django.conf import settings
from django.db.models.query import QuerySet

from rest_framework.renderers import JSONRenderer
from rest_framework.parsers import JSONParser

from mongoserializer.methods import DictToObject

import io
from math import ceil
from bson.objectid import ObjectId


def get_parsed_data(data):
    # data type is dict
    content = JSONRenderer().render(data)
    stream = io.BytesIO(content)
    return JSONParser().parse(stream)


def get_category_and_fathers(category):
    if category:
        if isinstance(category, QuerySet):
            category = category[0]
        category_and_fathers = [category]
        for i in range(category.level-1):
            category = category.father_category
            if category:
                category_and_fathers += [category]
        return category_and_fathers
    raise AttributeError('category is None')


def comment_save_to_mongo(comment_col, serializer, _id, request=None):
    if serializer.validated_data:
        data = get_parsed_data(serializer.validated_data)
        if _id:
            comment = comment_col.find_one({'_id': ObjectId(_id)})
        if comment.post:
            post_col = mongo_db.post
            if not change:
                post_col.update_one({'_id': ObjectId(comment.post)}, {'$push': {'comments': data}})
            else:
                post_col.update_one({'_id': ObjectId(comment.post), 'comments.id': comment.id}, {'$set': {'comments.$': data}})

        elif comment.product_id:
            product_col, foreignkey = settings.MONGO_PRODUCT_COL, comment.product_id
            if not change:
                product_col.update_one({'id': foreignkey}, {'$push': {'comments': data}})
            else:
                product_col.update_one({'id': foreignkey, 'comments.id': comment.id}, {'$set': {'comments.$': data}})
        else:      # this will prevent error in comment editing when there is not any post/product
            return None


def get_page_count(count, step, **kwargs):  # count can be a model class or instances of model class
    if isinstance(count, int):
        return ceil(count / step)
    import inspect
    if inspect.isclass(count):    # count is like: Product or other model class
        ceil(count.objects.filter(visible=True, **kwargs).count() / step)
    else:        # count is like <Queryset Product(1), Product(2), ....> or other model instances
        # ceil round up number, like: ceil(2.2)==3 ceil(3)==3
        return ceil(count.count() / step)
