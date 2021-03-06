"""
Google Analytics template tags and filters.
"""

from __future__ import absolute_import

import re

from django.conf import settings
from django.template import Library, Node, TemplateSyntaxError

from analytical.utils import is_internal_ip, disable_html, \
        get_required_setting, get_domain, AnalyticalException

def enumerate(sequence, start=0):
    """Copy of the Python 2.6 `enumerate` builtin for compatibility."""
    n = start
    for elem in sequence:
        yield n, elem
        n += 1


TRACK_SINGLE_DOMAIN = 1
TRACK_MULTIPLE_SUBDOMAINS = 2
TRACK_MULTIPLE_DOMAINS = 3

SCOPE_VISITOR = 1
SCOPE_SESSION = 2
SCOPE_PAGE = 3

PROPERTY_ID_RE = re.compile(r'^UA-\d+-\d+$')
SETUP_CODE = """
    <script type="text/javascript">

      var _gaq = _gaq || [];
      _gaq.push(['_setAccount', '%(property_id)s']);
      _gaq.push(['_trackPageview']);
      %(commands)s
      (function() {
        var ga = document.createElement('script'); ga.type = 'text/javascript'; ga.async = true;
        ga.src = ('https:' == document.location.protocol ? %(source_scheme)s) + %(source_url)s;
        var s = document.getElementsByTagName('script')[0]; s.parentNode.insertBefore(ga, s);
      })();

    </script>
"""
DOMAIN_CODE = "_gaq.push(['_setDomainName', '%s']);"
NO_ALLOW_HASH_CODE = "_gaq.push(['_setAllowHash', false]);"
ALLOW_LINKER_CODE = "_gaq.push(['_setAllowLinker', true]);"
CUSTOM_VAR_CODE = "_gaq.push(['_setCustomVar', %(index)s, '%(name)s', " \
        "'%(value)s', %(scope)s]);"
SITE_SPEED_CODE = "_gaq.push(['_trackPageLoadTime']);"
ANONYMIZE_IP_CODE = "_gaq.push (['_gat._anonymizeIp']);"
TRANSACTION_CODE = "_gaq.push(['_addTrans', '%(transactionId)s', '%(affiliation)s', "\
        "'%(total)s', '%(tax)s', '%(shipping)s', '%(city)s', '%(state)s', '%(country)s']);"
ITEM_CODE = "_gaq.push(['_addItem', '%(transactionId)s', '%(sku)s', '%(name)s', "\
        "'%(category)s', '%(price)s', '%(quantity)s']);"
SET_CODE = "_gaq.push(['_set', '%(key)s', '%(value)s']);"
TRACK_TRANSACTION_CODE = "_gaq.push(['_trackTrans']);"
DEFAULT_SOURCE = ("'https://ssl' : 'http://www'", "'.google-analytics.com/ga.js'")
DISPLAY_ADVERTISING_SOURCE = ("'https://' : 'http://'", "'stats.g.doubleclick.net/dc.js'")

register = Library()

@register.tag
def google_analytics(parser, token):
    """
    Google Analytics tracking template tag.

    Renders Javascript code to track page visits.  You must supply
    your website property ID (as a string) in the
    ``GOOGLE_ANALYTICS_PROPERTY_ID`` setting.
    """
    bits = token.split_contents()
    if len(bits) > 1:
        raise TemplateSyntaxError("'%s' takes no arguments" % bits[0])
    return GoogleAnalyticsNode()

class GoogleAnalyticsNode(Node):
    def __init__(self):
        self.property_id = get_required_setting(
                'GOOGLE_ANALYTICS_PROPERTY_ID', PROPERTY_ID_RE,
                "must be a string looking like 'UA-XXXXXX-Y'")

    def render(self, context):
        commands = self._get_domain_commands(context)
        commands.extend(self._get_custom_var_commands(context))
        commands.extend(self._get_other_commands(context))
        commands.extend(self._get_transaction_commands(context))
        if getattr(settings, 'GOOGLE_ANALYTICS_DISPLAY_ADVERTISING', False):
            source = DISPLAY_ADVERTISING_SOURCE
        else:
            source = DEFAULT_SOURCE
        html = SETUP_CODE % {'property_id': self.property_id,
                             'commands': " ".join(commands),
                             'source_scheme': source[0],
                             'source_url': source[1]}
        if is_internal_ip(context, 'GOOGLE_ANALYTICS'):
            html = disable_html(html, 'Google Analytics')
        return html

    def _get_domain_commands(self, context):
        commands = []
        tracking_type = getattr(settings, 'GOOGLE_ANALYTICS_TRACKING_STYLE',
                TRACK_SINGLE_DOMAIN)
        if tracking_type == TRACK_SINGLE_DOMAIN:
            pass
        else:
            domain = get_domain(context, 'google_analytics')
            if domain is None:
                raise AnalyticalException("tracking multiple domains with"
                        " Google Analytics requires a domain name")
            commands.append(DOMAIN_CODE % domain)
            commands.append(NO_ALLOW_HASH_CODE)
            if tracking_type == TRACK_MULTIPLE_DOMAINS:
                commands.append(ALLOW_LINKER_CODE)
        return commands

    def _get_custom_var_commands(self, context):
        values = (context.get('google_analytics_var%s' % i)
                for i in range(1, 6))
        vars = [(i, v) for i, v in enumerate(values, 1) if v is not None]
        commands = []
        for index, var in vars:
            name = var[0]
            value = var[1]
            try:
                scope = var[2]
            except IndexError:
                scope = SCOPE_PAGE
            commands.append(CUSTOM_VAR_CODE % locals())
        return commands

    def _get_transaction_commands(self, context):
        transaction = context.get('google_analytics_transaction')
        commands = []

        if not transaction:
            return commands
        if 'transactionId' not in transaction or 'total' not in transaction:
            raise AnalyticalException("transaction tracking requires a total"
                    " and a transactionId")

        transaction = dict({'affiliation': '', 'tax': '','shipping': '',
                            'city': '', 'state': '', 'country': ''},
                           **transaction)
        commands.append(TRANSACTION_CODE % transaction)

        items = context.get('google_analytics_items', [])
        for item in items:
            for required in ('sku', 'name', 'price', 'quantity'):
                if required not in item:
                    raise AnalyticalException("item requires %s variable" %
                                              required)
            item = dict({'transactionId': '', 'category': ''}, **item)
            commands.append(ITEM_CODE % item)

        default_local_currency = getattr(settings,
                                    'GOOGLE_ANALYTICS_ECOMMERCE_CURRENCY_CODE',
                                    None)
        local_currency = context.get('google_analytics_currency_code',
                                     default_local_currency)
        if local_currency:
            commands.append(SET_CODE % {'key': 'currencyCode',
                                        'value': local_currency})

        commands.append(TRACK_TRANSACTION_CODE)
        return commands

    def _get_other_commands(self, context):
        commands = []
        if getattr(settings, 'GOOGLE_ANALYTICS_SITE_SPEED', False):
            commands.append(SITE_SPEED_CODE)
        if getattr(settings, 'GOOGLE_ANALYTICS_ANONYMIZE_IP', False):
            commands.append(ANONYMIZE_IP_CODE)
        return commands

def contribute_to_analytical(add_node):
    GoogleAnalyticsNode()  # ensure properly configured
    add_node('head_bottom', GoogleAnalyticsNode)
