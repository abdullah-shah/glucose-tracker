import json
from datetime import datetime, timedelta

from django.views.generic import CreateView, UpdateView, DeleteView, \
    FormView, TemplateView
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render_to_response, HttpResponse
from django.template import RequestContext

from braces.views import LoginRequiredMixin
from django_datatables_view.base_datatable_view import BaseDatatableView

from . import utils
from .models import Glucose
from .reports import GlucoseCsvReport, ChartData, UserStats
from .forms import GlucoseCreateForm, GlucoseUpdateForm, GlucoseQuickAddForm, \
    GlucoseEmailReportForm, GlucoseFilterForm


DATE_FORMAT = '%m/%d/%Y'
TIME_FORMAT = '%I:%M %p'


@login_required
def filter_view(request):
    """
    Displays the glucose data table for the currently logged in user with
    filter options.

    The data is loaded by the GlucoseListJson view and rendered by the
    Datatables plugin via Javascript.
    """
    form = GlucoseFilterForm(request.user)
    form.fields['start_date'].initial = (datetime.now(
        tz=request.user.settings.time_zone) - timedelta(days=7))\
        .date().strftime(DATE_FORMAT)
    form.fields['end_date'].initial = datetime.now(
        tz=request.user.settings.time_zone).date().strftime(DATE_FORMAT)

    data = reverse('glucose_list_json')

    if request.method == 'POST' and request.is_ajax:
        params = request.POST

        # Create the URL query string and strip the last '&' at the end.
        data = ('%s?%s' % (reverse('glucose_list_json'), ''.join(
            ['%s=%s&' % (k, v) for k, v in params.iteritems()])))\
            .rstrip('&')

        return HttpResponse(json.dumps(data), content_type='application/json')

    return render_to_response(
        'glucoses/glucose_filter.html',
        {'form': form, 'data': data},
        context_instance=RequestContext(request),
    )


@login_required
def dashboard(request):
    """
    Displays the glucose data table for the currently logged in user. A form
    for quickly adding glucose values is also included.

    The data is loaded by the GlucoseListJson view and rendered by the
    Datatables plugin via Javascript.
    """
    form = GlucoseQuickAddForm()
    form.fields['category'].initial = utils.get_initial_category(
        request.user.settings.time_zone)

    return render_to_response(
        'core/dashboard.html',
        {'form': form},
        context_instance=RequestContext(request),
    )


@login_required
def chart_data_json(request):
    data = {}
    params = request.GET

    days = params.get('days', 0)
    name = params.get('name', '')
    if name == 'avg_by_category':
        avg_by_category = ChartData.get_avg_by_category(
            user=request.user, days=int(days))
        chart_data = avg_by_category
    elif name == 'avg_by_day':
        avg_by_day = ChartData.get_avg_by_day(
            user=request.user, days=int(days))
        chart_data = avg_by_day
    elif name == 'level_breakdown':
        level_breakdown = ChartData.get_level_breakdown(
            user=request.user, days=int(days))
        chart_data = level_breakdown
    elif name == 'count_by_category':
        count_by_category = ChartData.get_count_by_category(
            user=request.user, days=int(days))
        chart_data = count_by_category

    data['chart_data'] = chart_data

    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def stats_json(request):
    data = {'stats': UserStats(request.user).user_stats}

    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def quick_add(request):
    if request.method == 'POST' and request.is_ajax:
        form = GlucoseCreateForm(request.POST)
        if form.is_valid():
            user = request.user

            obj = form.save(commit=False)
            obj.user = request.user
            obj.record_date = datetime.now(tz=user.settings.time_zone).date()
            obj.record_time = datetime.now(tz=user.settings.time_zone).time()
            obj.save()

            message = {'success': True}

            return HttpResponse(json.dumps(message))
        else:
            message = {
                'success': False,
                'error': 'Please enter whole numbers only from 1 to 3000.'
            }

            return HttpResponse(json.dumps(message))

    raise PermissionDenied


class GlucoseChartsView(LoginRequiredMixin, TemplateView):
    template_name = 'glucoses/glucose_charts.html'


class GlucoseEmailReportView(LoginRequiredMixin, FormView):
    """
    Sends out an email containing the glucose data report.
    """
    success_url = '.'
    form_class = GlucoseEmailReportForm
    template_name = 'glucoses/glucose_email_report.html'

    def get_initial(self):
        return {'recipient': self.request.user.email,
                'message': 'Glucose data for %s.' % self.request.user.username}

    def form_valid(self, form):
        messages.add_message(self.request, messages.SUCCESS, 'Email sent!')
        return super(GlucoseEmailReportView, self).form_valid(form)

    def form_invalid(self, form):
        messages.add_message(self.request, messages.WARNING,
                             'Email not sent. Please try again.')
        return super(GlucoseEmailReportView, self).form_invalid(form)

    def post(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        if form.is_valid():
            report = GlucoseCsvReport(form.cleaned_data['start_date'],
                                      form.cleaned_data['end_date'],
                                      request.user)
            report.email(form.cleaned_data['recipient'],
                         form.cleaned_data['subject'],
                         form.cleaned_data['message'])

            return self.form_valid(form)
        else:
            return self.form_invalid(form)


class GlucoseCreateView(LoginRequiredMixin, CreateView):
    model = Glucose
    success_url = '/dashboard/'
    template_name = 'glucoses/glucose_create.html'
    form_class = GlucoseCreateForm

    def get_initial(self):
        time_zone = self.request.user.settings.time_zone
        record_date = datetime.now(tz=time_zone).date().strftime(DATE_FORMAT)
        record_time = datetime.now(tz=time_zone).time().strftime(TIME_FORMAT)

        return {
            'category': utils.get_initial_category(time_zone),
            'record_date': record_date,
            'record_time': record_time,
        }

    def form_valid(self, form):
        # Set the value of the 'user' field to the currently logged-in user.
        form.instance.user = self.request.user

        # Set the values of the record date and time to the current date and
        # time factoring in the user's timezone setting if they're not
        # specified.
        if not form.instance.record_date:
            form.instance.record_date = datetime.now(
                tz=self.request.user.settings.time_zone).date()

        if not form.instance.record_time:
            form.instance.record_time = datetime.now(
                tz=self.request.user.settings.time_zone).time()

        return super(GlucoseCreateView, self).form_valid(form)


class GlucoseDeleteView(LoginRequiredMixin, DeleteView):
    model = Glucose
    success_url = '/dashboard/'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # If the record's user doesn't match the currently logged-in user,
        # deny viewing/updating of the object by showing the 403.html
        # forbidden page. This can occur when the user changes the id in
        # the URL field to a record that the user doesn't own.
        if self.object.user != request.user:
            raise PermissionDenied
        else:
            return super(GlucoseDeleteView, self).get(request, *args, **kwargs)


class GlucoseListJson(LoginRequiredMixin, BaseDatatableView):
    model = Glucose

    columns = ['value', 'category', 'record_date', 'record_time', 'notes']
    order_columns = ['value', 'category', 'record_date', 'record_time', 'notes']
    max_display_length = 500

    def render_column(self, row, column):
        user_settings = self.request.user.settings
        low = user_settings.glucose_low
        high = user_settings.glucose_high
        target_min = user_settings.glucose_target_min
        target_max = user_settings.glucose_target_max

        if column == 'value':
            if row.value < low or row.value > high:
                return """<center><a href="%s"><font color="red">%s
                </font></a></center>""" % (
                    reverse('glucose_update', args=(row.id,)), row.value)
            elif row.value >= target_min and row.value <= target_max:
                return """<center><a href="%s"><font color="green">%s
                </font></a></center>""" % (
                    reverse('glucose_update', args=(row.id,)), row.value)
            else:
                return """<center><a href="%s">%s</a></center>""" % \
                   (reverse('glucose_update', args=(row.id,)), row.value)
        elif column == 'category':
            return '%s' % row.category.name
        elif column == 'record_date':
            return row.record_date.strftime('%m/%d/%Y')
        elif column == 'record_time':
            return row.record_time.strftime('%I:%M %p')
        else:
            return super(GlucoseListJson, self).render_column(row, column)

    def get_initial_queryset(self):
        """
        Filter records to show only entries from the currently logged-in user.
        """
        return Glucose.objects.by_user(self.request.user)

    def filter_queryset(self, qs):
        params = self.request.GET

        start_date = params.get('start_date', '')
        if start_date:
            qs = qs.filter(record_date__gte=datetime.strptime(
                start_date, DATE_FORMAT))
            
        end_date = params.get('end_date', '')
        if end_date:
            qs = qs.filter(record_date__lte=datetime.strptime(
                end_date, DATE_FORMAT))

        start_value = params.get('start_value', '')
        if start_value:
            qs = qs.filter(value__gte=start_value)
            
        end_value = params.get('end_value', '')
        if end_value:
            qs = qs.filter(value__lte=end_value)

        category = params.get('category', '')
        if category:
            qs = qs.filter(category=category)

        notes = params.get('notes', '')
        if notes:
            qs = qs.filter(notes__contains=notes)

        tags = params.get('tags', '')
        if tags:
            qs = qs.filter(tags__name=tags)

        return qs


class GlucoseUpdateView(LoginRequiredMixin, UpdateView):
    model = Glucose
    context_object_name = 'glucose'
    success_url = '/dashboard/'
    template_name = 'glucoses/glucose_update.html'
    form_class = GlucoseUpdateForm

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # If the record's user doesn't match the currently logged-in user,
        # deny viewing/updating of the object by showing the 403.html
        # forbidden page. This can occur when the user changes the id in
        # the URL field to a record that the user doesn't own.
        if self.object.user != request.user:
            raise PermissionDenied
        else:
            return super(GlucoseUpdateView, self).get(request, *args, **kwargs)