import inspect
import re

from twisted.spread import pb
from twisted.web import xmlrpc, soap

import ibid

class Processor(object):

    type = 'message'
    addressed = True
    processed = False
    priority = 0

    def __init__(self, name):
        self.name = name

        if self.processed and self.priority == 0:
            self.priority = 1500

        self.load_config()

    def load_config(self):
        if self.name in ibid.config.plugins:
            config = ibid.config.plugins[self.name]

            for name, value in config.items():
                setattr(self, name, value)

        self.setup()

    def setup(self):
        pass

    def process(self, event):
        if event.type != self.type:
            return

        if self.addressed and ('addressed' not in event or not event.addressed):
            return

        if not self.processed and event.processed:
            return

        found = False
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if hasattr(method, 'handler'):
                found = True
                if hasattr(method, 'pattern'):
                    match = method.pattern.search(event.message)
                    if match is not None:
                        if not hasattr(method, 'authorised') or auth_responses(event, self.permission):
                            event = method(event, *match.groups()) or event
                else:
                    event = method(event) or event

        if not found:
            raise RuntimeError(u'No handlers found in %s' % self)

        return event

def handler(function):
    function.handler = True
    return function

def match(regex):
    pattern = re.compile(regex, re.I)
    def wrap(function):
        function.handler = True
        function.pattern = pattern
        return function
    return wrap

def auth_responses(event, permission):
    if not ibid.auth.authorise(event, permission):
        event.notauthed = True
        return False

    return True

def authorise(function):
    function.authorised = True
    return function

class RPC(pb.Referenceable, xmlrpc.XMLRPC, soap.SOAPPublisher):

    def __init__(self, name):
        print "RPC instantiated with %s" % self.feature

    def _getFunction(self, functionPath):
        return getattr(self, 'remote_' % functionPath)

    def lookupFunction(self, functionName):
        return getattr(self, 'remote_' % functionName)
 
# vi: set et sta sw=4 ts=4:
