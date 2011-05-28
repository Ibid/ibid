# Copyright (c) 2009-2010, Michael Gorven, Stefano Rivera, Dominic Cleal
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.

from datetime import datetime
import re
import logging

from ibid.compat import any
from ibid.config import BoolOption, IntOption, ListOption
from ibid.db import IbidUnicode, DateTime, Integer, Table, Column, Base, \
                    VersionedSchema
from ibid.plugins import Processor, match, handler, authorise
from ibid.utils import plural

features = {'karma': {
    'description': u'Keeps track of karma for people and things.',
    'categories': ('remember',),
}}

log = logging.getLogger('plugins.karma')

class Karma(Base):
    __table__ = Table('karma', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('subject', IbidUnicode(64, case_insensitive=True), unique=True,
           nullable=False, index=True),
    Column('changes', Integer, nullable=False),
    Column('value', Integer, nullable=False),
    Column('time', DateTime, nullable=False),
    useexisting=True)

    class KarmaSchema(VersionedSchema):
        def upgrade_1_to_2(self):
            self.add_index(self.table.c.subject)
        def upgrade_2_to_3(self):
            self.alter_column(Column('subject', IbidUnicode(64), unique=True,
                                     nullable=False, index=True))
        def upgrade_3_to_4(self):
            self.drop_index(self.table.c.subject)
            self.alter_column(Column('subject',
                                     IbidUnicode(64, case_insensitive=True),
                                     unique=True, nullable=False, index=True),
                              force_rebuild=True)
            self.add_index(self.table.c.subject)

    __table__.versioned_schema = KarmaSchema(__table__, 4)

    def __init__(self, subject):
        self.subject = subject
        self.changes = 0
        self.value = 0
        self.time = datetime.utcnow()

class Set(Processor):
    usage = u'<subject>(++|--|==| ftw| ftl) [[reason]]'
    features = ('karma',)

    # Clashes with morse & math
    priority = 510

    permission = u'karma'

    increase = ListOption('increase',
                          'Suffixes which indicate increased karma',
                          ('++', ' ftw'))
    decrease = ListOption('decrease', 'Suffixes which indicate decreased karma',
                          ('--', ' ftl'))
    neutral = ListOption('neutral', 'Suffixes which indicate neutral karma',
                         ('==',))
    reply = BoolOption('reply', 'Acknowledge karma changes', False)
    public = BoolOption('public', 'Only allow karma changes in public', True)
    ignore = ListOption('ignore', 'Karma subjects to silently ignore', ())
    importance = IntOption('importance', 'Threshold for number of changes after'
                           " which a karma won't be forgotten", 0)

    def setup(self):
        # When not addressed, match karma changes in any text
        if self.addressed:
            matchpat = r'^(.+?)\s*(%s)\s*(?:[[{(]+\s*(.+?)\s*[\]})]+)?$'
        else:
            matchpat = r'(\S*\w\S*)(%s)(?:$|[\s,;\.\?!])'

        self.increase_reg = self.regex_tokens(self.increase)
        self.decrease_reg = self.regex_tokens(self.decrease)
        self.neutral_reg = self.regex_tokens(self.neutral)

        self.set.im_func.pattern = re.compile(
                matchpat % '|'.join(
                    self.increase_reg + self.decrease_reg + self.neutral_reg
                ), re.I | re.UNICODE | re.DOTALL)

    def regex_tokens(self, tokens):
        """ Turn configured tokens into regex versions """
        return [re.escape(t).replace(r'\ ', r'\s+') for t in tokens]

    def match_operators(self, roperators, adjust):
        return any(re.match(r, adjust) for r in roperators)

    @handler
    @authorise(fallthrough=False)
    def set(self, event, subject, adjust, reason=None):
        if reason is None:
            reason = event['message']['clean']

        if self.public and not event.public:
            event.addresponse(u'Karma must be done in public')
            return

        if subject.lower() in self.ignore:
            return

        karma = event.session.query(Karma).filter_by(subject=subject).first()
        if not karma:
            karma = Karma(subject)

        if self.match_operators(self.increase_reg, adjust.lower()):
            if subject.lower() == event.sender['nick'].lower():
                event.addresponse(u"You can't karma yourself!")
                return
            karma.changes += 1
            karma.value += 1
            change = u'Increased'
        elif self.match_operators(self.decrease_reg, adjust.lower()):
            karma.changes += 1
            karma.value -= 1
            change = u'Decreased'
        else:
            karma.changes += 2
            change = u'Increased and decreased'

        if karma.value == 0 and karma.changes <= self.importance:
            change = u'Forgotten (unimportant)'

            event.session.delete(karma)
        else:
            event.session.add(karma)
        event.session.commit()

        log.info(u"%s karma for '%s' by %s/%s (%s) because: %s",
                change, subject, event.account, event.identity, event.sender['connection'], reason)

        if self.reply:
            event.addresponse(u'%(subject)s now has %(value)s %(points)s of karma', {
                'subject': subject,
                'value': karma.value,
                'points': plural(karma.value, "point", "points"),
            })
        else:
            event.processed = True

class Get(Processor):
    usage = u"""karma for <subject>
    [reverse] karmaladder"""
    features = ('karma',)

    @match(r'^karma\s+(?:for\s+)?(.+)$')
    def handle_karma(self, event, subject):
        karma = event.session.query(Karma).filter_by(subject=subject).first()
        if not karma:
            event.addresponse(u'nobody cares, dude')
        elif karma.value == 0:
            event.addresponse(u'%s has neutral karma', subject)
        else:
            event.addresponse(u'%(subject)s has karma of %(value)s', {
                'subject': subject,
                'value': karma.value,
            })

    @match(r'^(reverse\s+)?karmaladder$')
    def ladder(self, event, reverse):
        karmas = event.session.query(Karma)
        if reverse:
            karmas = karmas.order_by(Karma.value.asc())
        else:
            karmas = karmas.order_by(Karma.value.desc())
        karmas = karmas.limit(30).all()

        if karmas:
            event.addresponse(u', '.join(
                u'%s: %s (%s)'
                % (karmas.index(karma), karma.subject, karma.value)
                for karma in karmas))
        else:
            event.addresponse(u"I don't really care about anything")

class Forget(Processor):
    usage = u'forget karma for <subject> [[reason]]'
    features = ('karma',)

    # Clashes with factoid
    priority = -10

    permission = u'karmaadmin'

    @match(r'^forget\s+karma\s+for\s+(.+?)(?:\s*[[{(]+\s*(.+?)\s*[\]})]+)?$')
    @authorise(fallthrough=False)
    def forget(self, event, subject, reason):
        karma = event.session.query(Karma).filter_by(subject=subject).first()
        if not karma:
            karma = Karma(subject)
            event.addresponse(u"I was pretty ambivalent about %s, anyway", subject)

        event.session.delete(karma)
        event.session.commit()

        log.info(u"Forgot karma for '%s' by %s/%s (%s) because: %s",
                subject, event.account, event.identity, event.sender['connection'], reason)
        event.addresponse(True)

# vi: set et sta sw=4 ts=4:
