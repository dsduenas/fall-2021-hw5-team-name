from __future__ import unicode_literals

from jinja2 import Template

from django.db import models
from django.db.models import Q
from django.utils.encoding import force_text, python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _

from mayan.apps.documents.models import Document, DocumentType

from .literals import (
    INCLUSION_AND, INCLUSION_CHOICES, INCLUSION_OR, OPERATOR_CHOICES
)
from .managers import SmartLinkManager


@python_2_unicode_compatible
class SmartLink(models.Model):
    """
    This model stores the basic fields for a smart link. Smart links allow
    linking documents using a programmatic method of conditions that mirror
    Django's database filter operations.
    """
    label = models.CharField(
        db_index=True, max_length=96, verbose_name=_('Label')
    )
    dynamic_label = models.CharField(
        blank=True, max_length=96, help_text=_(
            'Enter a template to render. '
            'Use Django\'s default templating language '
            '(https://docs.djangoproject.com/en/1.11/ref/templates/builtins/). '
            'The {{ document }} context variable is available.'
        ), verbose_name=_('Dynamic label')
    )
    enabled = models.BooleanField(default=True, verbose_name=_('Enabled'))
    document_types = models.ManyToManyField(
        to=DocumentType, verbose_name=_('Document types')
    )

    objects = SmartLinkManager()

    class Meta:
        ordering = ('label',)
        verbose_name = _('Smart link')
        verbose_name_plural = _('Smart links')

    def __str__(self):
        return self.label

    def get_dynamic_label(self, document):
        """
        If the smart links was created using a template label instead of a
        static label, resolve the template and return the result.
        """
        if self.dynamic_label:
            context = {'document': document}
            try:
                template = Template(self.dynamic_label)
                return template.render(**context)
            except Exception as exception:
                return _(
                    'Error generating dynamic label; %s' % force_text(
                        exception
                    )
                )
        else:
            return None

    def get_linked_document_for(self, document):
        """
        Execute the corresponding smart links conditions for the document
        provided and return the resulting document queryset.
        """
        if document.document_type.pk not in self.document_types.values_list('pk', flat=True):
            raise Exception(
                _(
                    'This smart link is not allowed for the selected '
                    'document\'s type.'
                )
            )

        smart_link_query = Q()

        context = {'document': document}

        for condition in self.conditions.filter(enabled=True):
            template = Template(condition.expression)

            condition_query = Q(**{
                '%s__%s' % (
                    condition.foreign_document_data, condition.operator
                ): template.render(**context)
            })
            if condition.negated:
                condition_query = ~condition_query

            if condition.inclusion == INCLUSION_AND:
                smart_link_query &= condition_query
            elif condition.inclusion == INCLUSION_OR:
                smart_link_query |= condition_query

        if smart_link_query:
            return Document.objects.filter(smart_link_query)
        else:
            return Document.objects.none()

    def resolve_for(self, document):
        return ResolvedSmartLink(
            smart_link=self, queryset=self.get_linked_document_for(
                document=document
            )
        )


class ResolvedSmartLink(SmartLink):
    """
    Proxy model to represent an already resolved smart link. Used for easier
    colums registration.
    """
    class Meta:
        proxy = True

    def get_label_for(self, document):
        return self.get_dynamic_label(document=document) or self.label


@python_2_unicode_compatible
class SmartLinkCondition(models.Model):
    """
    This model stores a single smart link condition. A smart link is a
    collection of one of more smart link conditions.
    """
    smart_link = models.ForeignKey(
        on_delete=models.CASCADE, related_name='conditions', to=SmartLink,
        verbose_name=_('Smart link')
    )
    inclusion = models.CharField(
        choices=INCLUSION_CHOICES, default=INCLUSION_AND,
        help_text=_('The inclusion is ignored for the first item.'),
        max_length=16
    )
    foreign_document_data = models.CharField(
        help_text=_('This represents the metadata of all other documents.'),
        max_length=128, verbose_name=_('Foreign document attribute')
    )
    operator = models.CharField(choices=OPERATOR_CHOICES, max_length=16)
    expression = models.TextField(
        help_text=_(
            'Enter a template to render. '
            'Use Django\'s default templating language '
            '(https://docs.djangoproject.com/en/1.11/ref/templates/builtins/). '
            'The {{ document }} context variable is available.'
        ), verbose_name=_('Expression')
    )
    negated = models.BooleanField(
        default=False, help_text=_('Inverts the logic of the operator.'),
        verbose_name=_('Negated')
    )
    enabled = models.BooleanField(default=True, verbose_name=_('Enabled'))

    class Meta:
        verbose_name = _('Link condition')
        verbose_name_plural = _('Link conditions')

    def __str__(self):
        return '%s foreign %s %s %s %s' % (
            self.get_inclusion_display(),
            self.foreign_document_data, _('not') if self.negated else '',
            self.get_operator_display(), self.expression
        )
