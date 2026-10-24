from django import forms

from .models import CrossingReport


class CrossingReportForm(forms.Form):
    state = forms.ChoiceField(choices=CrossingReport.STATE_CHOICES)
