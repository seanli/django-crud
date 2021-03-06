from copy import copy
import uuid
from pprint import pprint
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.shortcuts import render_to_response
from django import forms
from django.template.defaultfilters import striptags
from django.conf import settings
from django.utils.http import urlquote, urlquote_plus

from django.views.generic import ListView, DeleteView, CreateView, UpdateView
from django.views.generic.base import TemplateResponseMixin
from django.views.generic.detail import SingleObjectMixin, SingleObjectTemplateResponseMixin
from django.views.generic.list import MultipleObjectMixin, BaseListView
from django.views.generic.edit import ProcessFormView, FormView, ModelFormMixin
from mongoforms.forms import MongoFormMetaClass, MongoForm


import yaml
try:
    import json
except ImportError:
    import simplejson as json



registered_cruds = set()


DEFAULT_FORMAT = getattr(settings, 'CRUD_DEFAULT_FORMAT', "yaml")


class MongoSingleObjectMixin(object):
    def get_queryset(self):
        try:
            return SingleObjectMixin.get_queryset(self)
        except AttributeError:
            return self.model.objects()
    def get_form_class(self):
        try:
            self.model._meta.app_label
        except AttributeError:
            class Meta:
                document = self.model

            try:
                for key,value in self.model._fields.items():
                    if value.primary_key:
                        prep_fields = self.model._fields.keys()
                        Meta.fields = prep_fields

            except KeyError:
                pass


            if self.form_class is not None:
                return self.form_class
            else:
                class_name = self.model.__name__ + 'Form'
                return MongoFormMetaClass(class_name, (MongoForm,), {'Meta': Meta})

    def get_template_names(self):
         try:
             return SingleObjectTemplateResponseMixin.get_template_names(self)
         except AttributeError:
             return [self.template_name]



    def get_model_name(self):
        return self.model.__name__.lower()


    def get_context_object_name(self, obj):
        """
        Get the name to use for the object.
        """
        try:
            return SingleObjectMixin.get_context_object_name(self, obj)
        except AttributeError:
            return "object"

    def get_context_data(self, **kwargs):
        context = kwargs
        context_object_name = self.get_context_object_name(self.object)

        context['model_verbose_name_plural'] = self.model.__name__+"s"
        context['model_verbose_name'] = self.model.__name__

        context['model_name'] = model_name = self.model.__name__.lower()
        context["uuid"] = uuid.uuid4()

        context["crud_urls"] = {
            "cruds":reverse("cruds_list"),
            "create":reverse("crud_%s_create"%model_name),
            "load":reverse("crud_%s_load"%model_name, args=[DEFAULT_FORMAT]),
            "dump":reverse("crud_%s_dump"%model_name, args=[DEFAULT_FORMAT]),
            "index":reverse("crud_%s_list"%model_name),
        }

        if context_object_name:
            context[context_object_name] = self.object
        return context

class MongoMultipleObjectsMixin(object):
    def get_queryset(self):
        try:
            return MultipleObjectMixin.get_queryset(self)
        except AttributeError:
            return self.model.objects()


class CRUDDumpView(MongoMultipleObjectsMixin, BaseListView):

    def get(self, request, **kwargs):
        self.object_list = self.get_queryset()
        dumps = [obj.dump() for obj in self.object_list]
        if kwargs['format']=="yaml":
            yaml.add_representer(unicode, lambda dumper, value: dumper.represent_scalar(u'tag:yaml.org,2002:str', value))
            return HttpResponse(yaml.dump(dumps), mimetype='application/yaml')
        elif kwargs['format']=="json":
            return HttpResponse(json.dumps(dumps, ensure_ascii=False), mimetype='application/json')
        else:
            raise NotImplementedError


class FormUpload(forms.Form):
    """
    Form for uploading file
    """
    file = forms.FileField()
    erase_existent = forms.BooleanField(initial=True)

class CRUDLoadView(MongoMultipleObjectsMixin, FormView):
    model=None
    template_name = "crud_load.html"
    def get_form_class(self):
        return FormUpload

    def get(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        return self.render_to_response(self.get_context_data(form=form, format=kwargs["format"]))

    def post(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        if form.is_valid():
            if form.cleaned_data["erase_existent"]:
                self.model.drop_collection()

            d = form.cleaned_data["file"].read()
            print d
            if kwargs["format"]=="json":
                data = json.loads(d)
            elif kwargs["format"]=="yaml":
                data = yaml.load(d)
            else:
                raise NotImplementedError

            for objd in data:
                newobj = self.model.from_data(objd)
                newobj.save()
            return self.form_valid(form)
        else:
            return self.form_invalid(form, format=kwargs["format"])

    def form_invalid(self, form, format):
        return self.render_to_response(self.get_context_data(form=form, format=format))

    def get_context_data(self, **kwargs):
        context = super(CRUDLoadView, self).get_context_data(**kwargs)
        context["format"] = kwargs["format"]
        context['model_verbose_name_plural'] = self.model.__name__+"s"
        context['model_verbose_name'] = self.model.__name__

        context['model_name'] = model_name = self.model.__name__.lower()
        return context

    def get_success_url(self):
        return reverse("crud_%s_list"%self.model.__name__.lower())

class CRUDListView(MongoMultipleObjectsMixin, ListView):
    template_name = "crud_list.html"





    def get_context_data(self, **kwargs):
        context = super(CRUDListView, self).get_context_data(**kwargs)

        #TODO: unify the following piece of sh... code in all views. Also ability to customize verbose_name
        #TODO: and verbose_name_plural for models needed. Maybe create a subclass of Document for crud
        #TODO: since mongoengine does not provide support for meta options in theirs document?
        context['model_verbose_name_plural'] = self.model.__name__+"s"
        context['model_verbose_name'] = self.model.__name__

        context['model_name'] = model_name = self.model.__name__.lower()
        context['crud_object_list'] = []
        context["crud_urls"] = {
            "cruds":reverse("cruds_list"),
            "create":reverse("crud_%s_create"%model_name),
            "load":reverse("crud_%s_load"%model_name, args=[DEFAULT_FORMAT]),
            "dump":reverse("crud_%s_dump"%model_name, args=[DEFAULT_FORMAT]),
        }
        for obj in context['object_list']:
            crud_obj = {}
            crud_obj["object"] = obj
            crud_obj["name"] = unicode(obj)
            crud_obj["url_edit"] = reverse("crud_%s_update"%model_name, kwargs={"pk":urlquote_plus(obj.pk)})
            crud_obj["url_delete"] = reverse("crud_%s_delete"%model_name, kwargs={"pk":urlquote_plus(obj.pk)})
            context['crud_object_list'].append(crud_obj)
        context["url_create"] = reverse("crud_%s_create"%model_name)

        return context


class CRUDDeleteView(MongoSingleObjectMixin, DeleteView):
    template_name = "crud_delete.html"



    def get_success_url(self):
        return reverse("crud_%s_list"%self.get_model_name())
    
    
class CRUDUpdateView(MongoSingleObjectMixin, UpdateView):
    template_name = "crud_update.html"


    def get_success_url(self):
        return reverse("crud_%s_update"%self.get_model_name(), kwargs={"pk":urlquote_plus(self.object.pk)})


class AjaxForm(object):
    def errors_as_json(self, strip_tags=False):
        error_summary = {}
        errors = {}
        for error in self.errors.iteritems():
            errors.update({error[0]: unicode(striptags(error[1])\
            if strip_tags else error[1])})
        error_summary.update({'errors': errors})
        return error_summary
    
class AjaxMixin(object):
    def form_valid(self, form):
        ModelFormMixin.form_valid(self, form)
        return HttpResponse(json.dumps({'success':True, 'object':form.instance.dump(), "object_pk":unicode(form.instance.pk)}, ensure_ascii=False),
                            mimetype='application/json')

    def form_invalid(self, form):
        return HttpResponse(json.dumps(form.errors_as_json(), ensure_ascii=False),
                            mimetype='application/json')

    def get_form_class(self):
        try:
            #fixme: detect mongo model
            self.model._meta.app_label
        except AttributeError:
            # The inner Meta class fails if model = model is used for some reason.
            tmp_model = self.model
            # TODO: we should be able to construct a ModelForm without creating
            # and passing in a temporary inner class.
            class Meta:
                document = tmp_model


            if self.form_class is not None:
                class_name = self.model.__name__ + 'CrudAjaxForm'
                return MongoFormMetaClass(class_name, (AjaxForm, self.form_class,), {'Meta': self.form_class.Meta})

            else:
                class_name = self.model.__name__ + 'CrudAjaxForm'
                return MongoFormMetaClass(class_name, (AjaxForm, MongoForm,), {'Meta': Meta})


class CRUDCreateView(MongoSingleObjectMixin, CreateView):
    template_name = "crud_create.html"

    def get_success_url(self):
        return reverse("crud_%s_update"%self.get_model_name(), kwargs={"pk":urlquote_plus(self.object.pk)})

class CRUDCreateAjaxView(AjaxMixin, CRUDCreateView):
    template_name = "crud_create_ajax.html"
    def get_context_data(self, **kwargs):
        context = super(CRUDCreateAjaxView, self).get_context_data(**kwargs)
        context["url_self"] = reverse("crud_%s_create.ajax"%self.model.__name__.lower())
        return context


class CRUDUpdateAjaxView(AjaxMixin, CRUDUpdateView):
    template_name = "crud_update_ajax.html"
    def get_context_data(self, **kwargs):
        context = super(CRUDUpdateAjaxView, self).get_context_data(**kwargs)
        context["url_self"] = reverse("crud_%s_update.ajax"%self.model.__name__.lower(), kwargs={"pk":urlquote_plus(self.object.pk)})
        return context

def cruds_list_view(request):
    cruds = []
    for model_name in copy(registered_cruds):
        cruds.append({ "url_list":reverse("crud_%s_list"%model_name),
                          "url_create":reverse("crud_%s_create"%model_name),
                          "name":model_name.capitalize()})
    return render_to_response("cruds_list.html", {"cruds": cruds})
