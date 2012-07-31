# Copyright (c) 2009-2011, Michael Gorven, Stefano Rivera
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.
#
# The indefinite_article function follows an algorithm by Damian Conway
# as published in CPAN package Lingua-EN-Inflect-1.891 under the GNU GPL
# (version 1 or later) and Artistic License 1.0.

import codecs
from gzip import GzipFile
from htmlentitydefs import name2codepoint
from locale import getpreferredencoding
import logging
import os
import os.path
import re
import socket
from StringIO import StringIO
from sys import version_info
from threading import Lock
import time
from urllib import urlencode, quote
import urllib2
from urlparse import urlparse, urlunparse
import zlib
from subprocess import Popen, PIPE

import dateutil.parser
from dateutil.tz import tzlocal, tzutc
from pkg_resources import resource_exists, resource_filename

import ibid
from ibid.compat import defaultdict, json

log = logging.getLogger('utils')

def ago(delta, units=None):
    parts = []

    for unit, value in (
            ('year', delta.days/365), ('month', delta.days/30 % 12),
            ('day', delta.days % 30), ('hour', delta.seconds/3600),
            ('minute', delta.seconds/60 % 60), ('second', delta.seconds % 60),
            ('millisecond', delta.microseconds/1000)):
        if value > 0 and (unit != 'millisecond' or len(parts) == 0):
            parts.append('%s %s%s' % (value, unit, value != 1 and 's' or ''))
            if units and len(parts) >= units:
                break

    formatted =  ' and '.join(parts)
    return formatted.replace(' and ', ', ', len(parts)-2)

def decode_htmlentities(text):
    replace = lambda match: unichr(int(match.group(1)))
    text = re.sub("&#(\d+);", replace, text)

    replace = lambda match: match.group(1) in name2codepoint and unichr(name2codepoint[match.group(1)]) or match.group(0)
    text = re.sub("&(\w+);", replace, text)
    return text

downloads_in_progress = defaultdict(Lock)
def cacheable_download(url, cachefile, headers={}, timeout=60):
    """Download url to cachefile if it's modified since cachefile.
    Specify cachefile in the form pluginname/cachefile.
    Returns complete path to downloaded file."""

    downloads_in_progress[cachefile].acquire()
    try:
        f = _cacheable_download(url, cachefile, headers, timeout)
    finally:
        downloads_in_progress[cachefile].release()

    return f

def _cacheable_download(url, cachefile, headers={}, timeout=60):
    # We do allow absolute paths, for people who know what they are doing,
    # but the common use case should be pluginname/cachefile.
    if cachefile[0] not in (os.sep, os.altsep):
        cachedir = ibid.config.plugins.get('cachedir', None)
        if not cachedir:
            cachedir = os.path.join(ibid.options['base'], 'cache')
        elif cachedir[0] == "~":
            cachedir = os.path.expanduser(cachedir)
        cachedir = os.path.abspath(cachedir)

        plugindir = os.path.join(cachedir, os.path.dirname(cachefile))
        if not os.path.isdir(plugindir):
            os.makedirs(plugindir)

        cachefile = os.path.join(cachedir, cachefile)

    exists = os.path.isfile(cachefile)

    req = urllib2.Request(iri_to_uri(url))
    for name, value in headers.iteritems():
        req.add_header(name, value)
    if not req.has_header('user-agent'):
        req.add_header('User-Agent', 'Ibid/' + (ibid_version() or 'dev'))

    if exists:
        if os.path.isfile(cachefile + '.etag'):
            f = file(cachefile + '.etag', 'r')
            req.add_header("If-None-Match", f.readline().strip())
            f.close()
        else:
            modified = os.path.getmtime(cachefile)
            modified = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(modified))
            req.add_header("If-Modified-Since", modified)

    kwargs = {}
    if version_info[1] >= 6:
        kwargs['timeout'] = timeout
    else:
        socket.setdefaulttimeout(timeout)
    try:
        try:
            connection = urllib2.urlopen(req, **kwargs)
        except urllib2.HTTPError, e:
            if e.code == 304 and exists:
                return cachefile
            else:
                raise
    finally:
        if version_info[1] < 6:
            socket.setdefaulttimeout(None)

    data = connection.read()

    compression = connection.headers.get('content-encoding')
    if compression:
        if compression.lower() == "deflate":
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
        elif compression.lower() == "gzip":
            compressedstream = StringIO(data)
            gzipper = GzipFile(fileobj=compressedstream)
            data = gzipper.read()

    etag = connection.headers.get('etag')
    if etag:
        f = file(cachefile + '.etag', 'w')
        f.write(etag + '\n')
        f.close()

    outfile = file(cachefile, 'wb')
    outfile.write(data)
    outfile.close()

    return cachefile

def file_in_path(program):
    path = os.environ.get("PATH", os.defpath).split(os.pathsep)
    path = [os.path.join(dir, program) for dir in path]
    path = [True for file in path if os.path.isfile(file)]
    return bool(path)

def unicode_output(output, errors="strict"):
    return unicode(output, getpreferredencoding(), errors)

def ibid_version():
    try:
        from pkg_resources import get_distribution, DistributionNotFound
        try:
            package = get_distribution('Ibid')
            if package and hasattr(package, 'version'):
                return package.version
        except DistributionNotFound:
            pass
    except ImportError:
        pass

def format_date(timestamp, length='datetime', tolocaltime=True):
    "Format a UTC date for displaying in a response"

    defaults = {
            u'datetime_format': u'%Y-%m-%d %H:%M:%S %Z',
            u'date_format': u'%Y-%m-%d',
            u'time_format': u'%H:%M:%S %Z',
    }

    length += '_format'
    format = ibid.config.plugins.get(length, defaults[length])

    if tolocaltime:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=tzutc())
        timestamp = timestamp.astimezone(tzlocal())

    return unicode(timestamp.strftime(format.encode('utf8')), 'utf8')

def parse_timestamp(timestamp):
    "Parse a machine timestamp, convert to UTC, strip timezone"
    dt = dateutil.parser.parse(timestamp)
    if dt.tzinfo:
        dt = dt.astimezone(tzutc())
        dt = dt.replace(tzinfo=None)
    return dt

class JSONException(Exception):
    pass

def iri_to_uri(url):
    "Expand an IDN hostname and UTF-8 encode the path of a unicode URL"
    parts = list(urlparse(url))
    username, passwd, host, port = re.match(
        r'^(?:(.*)(?::(.*))?@)?(.*)(?::(.*))?$', parts[1]).groups()
    parts[1] = ''
    if username:
        parts[1] = quote(username.encode('utf-8'))
        if passwd:
            parts[1] += ':' + quote(passwd.encode('utf-8'))
        parts[1] += '@'
    if host:
        if parts[0].lower() in ('http', 'https', 'ftp'):
            parts[1] += host.encode('idna')
        else:
            parts[1] += quote(host.encode('utf-8'))
    if port:
        parts[1] += ':' + quote(port.encode('utf-8'))

    parts[2] = quote(parts[2].encode('utf-8'), '/%')
    return urlunparse(parts).encode('utf-8')

_url_regex = None

def url_regex():
    global _url_regex
    if _url_regex is not None:
        return _url_regex

    tldfile = locate_resource('ibid', 'data/tlds-alpha-by-domain.txt')
    if tldfile:
        f = file(tldfile, 'r')
        tlds = [tld.strip().lower() for tld in f.readlines()
                if not tld.startswith('#')]
        f.close()
    else:
        log.warning(u"Couldn't open TLD list, falling back to minimal default")
        tlds = 'com.org.net.za'.split('.')

    _url_regex = (
        r'(?:\w+://|(?:www|ftp)\.)\S+?' # Match an explicit URL or guess by www.
        r'|[^@\s:/]+\.(?:%s)(?:/\S*?)?' # Guess at the URL based on TLD
    ) % '|'.join(tlds)

    return _url_regex

def is_url(url):
    return re.match('^' + url_regex() + '$', url, re.I) is not None

def generic_webservice(url, params={}, headers={}):
    "Retreive data from a webservice"

    for key in params:
        if isinstance(params[key], unicode):
            params[key] = params[key].encode('utf-8')

    if params:
        url = iri_to_uri(url) + '?' + urlencode(params)

    req = urllib2.Request(url, headers=headers)
    if not req.has_header('user-agent'):
        req.add_header('User-Agent', 'Ibid/' + (ibid_version() or 'dev'))

    f = urllib2.urlopen(req)
    data = f.read()
    f.close()
    return data

def json_webservice(url, params={}, headers={}):
    "Request data from a JSON webservice, and deserialise"

    data = generic_webservice(url, params, headers)
    try:
        return json.loads(data)
    except ValueError, e:
        raise JSONException(e)

def human_join(items, separator=u',', conjunction=u'and'):
    "Create a list like: a, b, c and d"
    items = list(items)
    separator += u' '
    return ((u' %s ' % conjunction)
            .join(filter(None, [separator.join(items[:-1])] + items[-1:])))

def plural(count, singular, plural):
    "Return singular or plural depending on count"
    if abs(count) == 1:
        return singular
    return plural

def locate_resource(path, filename):
    "Locate a resource either within the botdir or the source tree"
    fspath = os.path.join(*(
        [ibid.options['base']] + path.split('.') + [filename]
    ))
    if os.path.exists(fspath):
        return fspath
    if not resource_exists(path, filename):
        return None
    return resource_filename(path, filename)

def get_process_output(command, input=None):
    process = Popen(command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    output, error = process.communicate(input)
    code = process.wait()
    return output, error, code

def indefinite_article(noun_phrase):
    # algorithm adapted from CPAN package Lingua-EN-Inflect-1.891 by Damian Conway
    m = re.search('\w+', noun_phrase, re.UNICODE)
    if m:
        word = m.group(0)
    else:
        return u'an'

    wordi = word.lower()
    for anword in ('euler', 'heir', 'honest', 'hono'):
        if wordi.startswith(anword):
            return u'an'

    if wordi.startswith('hour') and not wordi.startswith('houri'):
        return u'an'

    if len(word) == 1:
        if wordi in 'aedhilmnorsx':
            return u'an'
        else:
            return u'a'

    if re.match(r'(?!FJO|[HLMNS]Y.|RY[EO]|SQU|'
                  r'(F[LR]?|[HL]|MN?|N|RH?|S[CHKLMNPTVW]?|X(YL)?)[AEIOU])'
                  r'[FHLMNRSX][A-Z]', word):
        return u'an'

    for regex in (r'^e[uw]', r'^onc?e\b',
                    r'^uni([^nmd]|mo)','^u[bcfhjkqrst][aeiou]'):
        if re.match(regex, wordi):
            return u'a'

    # original regex was /^U[NK][AIEO]?/ but that matches UK, UN, etc.
    if re.match('^U[NK][AIEO]', word):
        return u'a'
    elif word == word.upper():
        if wordi[0] in 'aedhilmnorsx':
            return u'an'
        else:
            return u'a'

    if wordi[0] in 'aeiou':
        return u'an'

    if re.match(r'^y(b[lor]|cl[ea]|fere|gg|p[ios]|rou|tt)', wordi):
        return u'an'
    else:
        return u'a'

def get_country_codes():
    filename = cacheable_download(
            'http://www.iso.org/iso/list-en1-semic-3.txt',
            'lookup/iso-3166-1_list_en.txt')

    f = codecs.open(filename, 'r', 'UTF-8')
    countries = {
        u'AC': u'Ascension Island',
        u'UK': u'United Kingdom',
        u'SU': u'Soviet Union',
        u'EU': u'European Union',
        u'TP': u'East Timor',
        u'YU': u'Yugoslavia',
    }

    started = False
    for line in f:
        line = line.strip()
        if not started:
            started = True
            continue
        if ';' in line:
            country, code = line.split(u';')
            country = country.lower()
            # Hack around http://bugs.python.org/issue7008
            country = country.title().replace(u"'S", u"'s")
            countries[code] = country

    f.close()

    return countries

def identity_name(event, identity):
    if event.identity == identity.id:
        return u'you'
    elif event.source == identity.source:
        return identity.identity
    else:
        return u'%s on %s' % (identity.identity, identity.source)

# vi: set et sta sw=4 ts=4:
