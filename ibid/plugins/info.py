from subprocess import Popen, PIPE

from nickometer import nickometer

import ibid
from ibid.plugins import Processor, match, RPC

help = {}

help['fortune'] = u'Returns a random fortune.'
class Fortune(Processor, RPC):
    """fortune"""
    feature = 'fortune'

    fortune = 'fortune'

    def __init__(self, name):
        super(Fortune, self).__init__(name)
        RPC.__init__(self)

    @match(r'^fortune$')
    def handler(self, event):
        event.addresponse(self.remote_fortune() or u"Couldn't execute fortune")

    def remote_fortune(self):
        fortune = Popen(self.fortune, stdout=PIPE, stderr=PIPE)
        output, error = fortune.communicate()
        code = fortune.wait()

        if code == 0:
            return output.strip()
        else:
            return None

help['nickometer'] = u'Calculates how lame a nick is.'
class Nickometer(Processor):
    """nickometer [<nick>] [with reasons]"""
    feature = 'nickometer'
    
    @match(r'^(?:nick|lame)-?o-?meter(?:(?:\s+for)?\s+(.+?))?(\s+with\s+reasons)?$')
    def handle_nickometer(self, event, nick, wreasons):
        nick = nick or event.who
        score, reasons = nickometer(str(nick))
        event.addresponse(u"%s is %s%% lame" % (nick, score))
        if wreasons:
            event.addresponse(u', '.join(['%s (%s)' % reason for reason in reasons]))

help['man'] = u'Retrieves information from manpages.'
class Man(Processor):
    """man [<section>] <page>"""
    feature = 'man'

    man = 'man'

    @match(r'^man\s+(?:(\d)\s+)?(\S+)$')
    def handle_man(self, event, section, page):
        command = [self.man, page]
        if section:
            command.insert(1, section)
        man = Popen(command, stdout=PIPE, stderr=PIPE)
        output, error = man.communicate()
        code = man.wait()

        if code != 0:
            event.addresponse(u'Manpage not found')
        else:
            lines = [unicode(line, 'utf-8', errors='replace') for line in output.splitlines()]
            index = lines.index('NAME')
            if index:
                event.addresponse(lines[index+1].strip())
            index = lines.index('SYNOPSIS')
            if index:
                event.addresponse(lines[index+1].strip())
        

# vi: set et sta sw=4 ts=4:
