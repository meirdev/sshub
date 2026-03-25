from django import forms


class CodeMirrorWidget(forms.Textarea):
    template_name = "core/widgets/codemirror.html"

    class Media:
        js = ("core/js/codemirror_init.js",)
