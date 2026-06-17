import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.template import Template, Context

t = Template("{% load sj_extras %}{% if 'interview_scheduled' in 'interview_scheduled,interviewing'|split:',' %}YES{% else %}NO{% endif %}")
print(t.render(Context({})))
