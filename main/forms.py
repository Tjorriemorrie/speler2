from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django import forms
from django.urls import reverse


class URLForm(forms.Form):
    refresh = forms.BooleanField(widget=forms.HiddenInput(), initial=True)
    url = forms.CharField(label='URL', max_length=500)

    def __init__(self, song_id, *args, **kwargs):
        """Create helper."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.attrs = {
            'hx-get': reverse('lyric_view', kwargs={'song_id': song_id}),
            'hx-target': '#lyrics-container',
            'hx-swap': 'innerHTML',
        }
        self.helper.form_method = 'GET'
        self.helper.add_input(Submit('submit', 'Retry', css_class='btn btn-primary'))
