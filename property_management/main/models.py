from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db import models

from .model_methods import set_levels_afterthis_all_childes_id


group_choices = [(key, str(key)) for key in range(1, 11)]
genre_choices = [(_('attribute'), 'attribute'), (_('filter'), 'filter'), (_('both'), 'both')]
symbole_choices = [('None', 'None'), (_('icon'), 'icon'), (_('color'), 'color')]  # None has default translation
class Filter(models.Model):
    group = models.PositiveIntegerField(_('group'), choices=group_choices)
    name = models.CharField(_('name'), unique=True, max_length=25)        # name for quering.
    verbose_name = models.CharField(_('verbose name'), max_length=25)     # name for showing. (to user).  for example you have two filter with names: "system amel goshi", "system amele laptop" but both of them have 'system amel' as verbose name.
    genre = models.CharField(_('genre'), max_length=25, choices=genre_choices)
    symbole = models.CharField(_('symbole'), max_length=25, choices=symbole_choices)
    #filter_attributes
    #category_set

    class Meta:
        verbose_name = _('Filter')
        verbose_name_plural = _('Filters')

    def __str__(self):
        return str(self.name)


class Category(models.Model):                                  #note: supose roor2 object,  category2.father_category determine father of category2 and category2.child_categories is list of category2's childer,  category with level=1 can has eny father!
    name = models.CharField(_('name'), unique=True, max_length=50)
    slug = models.SlugField(_('slug'), allow_unicode=True, db_index=False)
    level = models.PositiveSmallIntegerField(_('level'), default=1, validators=[MinValueValidator(1), MaxValueValidator(6)])        #important: in main/views/ProductCategoryList & ProductDetail and in main/methods/get_posts_products_by_category   we used MaxValueValidator with its posation in validator, so validator[1] must be MaxValueValidator otherwise will raise error.
    father_category = models.ForeignKey('self', related_name='child_categories', related_query_name='childs', null=True, blank=True, on_delete=models.CASCADE, verbose_name=_('father category'))        #if category.level>1 will force to filling this field.
    levels_afterthis = models.PositiveSmallIntegerField(default=0, blank=True)                         #in field neshan midahad chand sath farzand darad in pedar, masalam: <category(1) digital>,  <category(2) mobail>,  <category(3) samsung> farz konid mobail pedare samsung,  digital pedare mobail ast(<category(1) digital>.level=1,  <category(2) mobail>.level=2,  <category(3) samsung>.level=3)   . bala sare digital dar in mesal 2 sath farzand mibashad( mobail va samsung pas <category(1) digital>.levels_afterthis = 2   va <category(2) mobail>.levels_afterthis=1  va <category(3) samsung>.levels_afterthis=0
    previous_father_id = models.PositiveSmallIntegerField(null=True, blank=True)                         #supose you change category.father_category, we cant understant prevouse father was what in Category.save(ony new edited father_category is visible) so we added this field
    all_childes_id = models.TextField(default='', blank=True)                      #list all chiles of that object in this structure: "1,2,3,4"    if this field name was chiles_id maybe raise problem with related_query_name of father_category or other.
    post_product = models.CharField(_('post or product'), max_length=10, default='product')      #this should be radio button in admin panel.
    filters = models.ManyToManyField(Filter, through='Category_Filters', blank=True, verbose_name=_('filters'))
    #child_categories
    #product_set

    class Meta:
        ordering = ('level',)                    #main/views/ProductList/sidebarcategory_link affect order of Category.  ('level', '-father_category_id') '-father_category_id' make in ProductCategoryList products order from last to first (reverse order) -father_category_id  will make childs with same father be in together. and '-' will make decending order like ordering django admin for 'order by ids' means lower ids will go to down.(tested)
        verbose_name = _('category')
        verbose_name_plural = _('categories')

    def __str__(self):
        return str(self.level) + ' - ' + self.name

    def clean_fields(self, exclude=None):
        if self.level:                                                   #why we put this line?  answer: in adding category, self.father_category is None and raise erro if: 'self.level > 1'
            if self.level > 1 and not self.father_category:                  #other conditions will control by form eazy (for example if self.level==1 father_category must be None)
                raise ValidationError({'father_category': [_('This field is required for level more than 1.')]})
        super().clean_fields(exclude=None)

    def save(self, *args, **kwargs):
        previous_father_queryset = Category.objects.filter(id=self.previous_father_id).select_related('father_category__'*4+'father_category') if self.previous_father_id else None
        self.previous_father_id = self.father_category_id if self.father_category_id else None
        super().save(*args, **kwargs)
        category_queryset = Category.objects.filter(id=self.id).select_related('father_category__'*5+'father_category')    #instead using 6 logn father_category we used more breafer format!

        categories_before_join, categories_after_join = set_levels_afterthis_all_childes_id(previous_father_queryset, category_queryset, Category._meta.get_field('level').validators[1].limit_value)
        Category.objects.bulk_update(categories_before_join, ['levels_afterthis', 'all_childes_id']) if categories_before_join else None
        Category.objects.bulk_update(categories_after_join, ['levels_afterthis', 'all_childes_id']) if categories_after_join else None

    def delete(self, using=None, keep_parents=False):
        id = self.id
        dell = super().delete(using, keep_parents)
        previous_father_queryset = Category.objects.filter(id=self.father_category_id).select_related('father_category__'*5+'father_category') if self.father_category_id else None
        self.id, self.father_category, self.father_category_id = id, None, None                                               #we need self.id in list_childes_id
        categories_before_join, categories_after_join = set_levels_afterthis_all_childes_id(previous_father_queryset, [self], Category._meta.get_field('level').validators[1].limit_value, delete=True)
        Category.objects.bulk_update(categories_before_join, ['levels_afterthis', 'all_childes_id']) if categories_before_join else None
        return dell


class Category_Filters(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, verbose_name=_('category'))
    filter = models.ForeignKey(Filter, on_delete=models.CASCADE, verbose_name=_('filter'))

    class Meta:
        verbose_name = _('Category Filter')
        verbose_name_plural = _('Category Filters')

    def __str__(self):
        return _('Category Filters') + str(self.id)

Category_Filters._meta.auto_created = True                        #if you dont put this you cant use filter_horizontal in admin.py for  Filter.categories or other manytomany fields that use Filter_Categories.
