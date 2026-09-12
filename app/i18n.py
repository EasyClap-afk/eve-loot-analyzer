"""UI-only localization. Stored values, type names and domain codes stay unchanged."""
import re
from .translations import CATALOG

_language='pl'

def set_language(language):
    global _language
    _language=language if language in ('pl','en') else 'pl'

def language():
    return _language

def tr(source,**values):
    translated=CATALOG.get(source,{}).get(_language,source)
    return translated.format(**values) if values else translated

def message(source):
    """Localize legacy domain messages at display time, including saved snapshots."""
    source=str(source)
    if source in CATALOG:return tr(source)
    for template,entry in CATALOG.items():
        if '{' not in template:continue
        names=re.findall(r'\{([a-zA-Z_][a-zA-Z_0-9]*)\}',template)
        if not names:continue
        pattern=re.escape(template)
        for name in names:pattern=pattern.replace(re.escape('{'+name+'}'),f'(?P<{name}>.*?)',1)
        match=re.fullmatch(pattern,source,re.DOTALL)
        if match:return tr(template,**{k:error_text(v) if k=='error' else v for k,v in match.groupdict().items()})
    # Raw API/library details remain in logs; show an actionable localized error.
    if 'HTTPStatusError' in source or 'error ' in source.lower() and 'https://' in source:
        code=re.search(r'\b([45]\d\d)\b',source)
        return tr('HTTP error {code}. Try again later; details are in the log.',code=code[1] if code else '?')
    if 'timed out' in source.lower():return tr('The request timed out. Try again.')
    return source

def error_text(source):
    aliases={'access_denied':'SSO access denied. Please authorize the requested scopes.',
             'Signature verification failed':'The token signature is invalid. Please log in again.',
             'Signature has expired':'The token has expired. Please log in again.'}
    source=str(source)
    if source in aliases:return tr(aliases[source])
    translated=message(source)
    if translated!=source or source in CATALOG:return translated
    if 'connect' in source.lower() or 'getaddrinfo' in source.lower():
        return tr('Could not connect. Check your internet connection and try again.')
    return tr('Unexpected error. See the log in the Data folder.')
