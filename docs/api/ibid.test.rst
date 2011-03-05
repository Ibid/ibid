:mod:`ibid.test` -- Ibid Testing
================================

.. module:: ibid.test
   :synopsis: Ibid Testing
.. moduleauthor:: Ibid Core Developers

End-to-end testing
------------------

.. class:: PluginTestCase

   A subclass of Twisted Trial's
   `unittest.TestCase <http://twistedmatrix.com/documents/8.2.0/api/twisted.trial.unittest.TestCase.html>`_.
   It sets up an environment much like a running Ibid including a clean SQLite
   database, and loads the specified plugins,

   .. attribute:: load

      List: strings naming plugins to be loaded before running tests.

      Default: empty

   .. attribute:: noload

      List: strings naming plugins *not* to be loaded.

      Default: empty

   .. attribute:: load_base

      Boolean: whether to load a small set of base plugins (currently, just core).

      Default: ``True``

   .. attribute:: load_configured

      Boolean: load all configured modules (excluding :attr:`noload`).

      Default: if :attr:`load` is empty, ``True``; otherwise, ``False``.

   .. attribute:: username

      String: the default username/nick in events created by the
      :func:`make_event` method.

      Default: ``u'user'``

   .. attribute:: public

      Boolean: whether or not the events created by :func:`make_event` are
      public.

      Default: ``False``

   .. attribute:: network

      Boolean: whether or not the test uses the external network. Used to
      skip tests in networkless environments (where the environment variable
      :envvar:`IBID_NETWORKLESS_TEST` is defined).

      Default: ``False``

   .. method:: setUp()

      If you override this method, make sure you call
      :meth:`PluginTestCase.setUp()`.

   .. method:: tearDown()

      If you override this method, make sure you call
      :meth:`PluginTestCase.tearDown()`.


   .. method:: make_event(message=None, type=u'message')

      Create and return an event on the test source, from the test user, of
      type *type*.

   .. method:: responseMatches(event, regex)

      Process *event* (either an event or a string to be treated as a
      message from the test user on the test source), and return a 3-tuple of
      (result, event, responses); result is a bool indicating whether the
      response matches *regex* (either a regex string or a compiled regex).

      The other two elements give more information: *event* is the processed
      event; *responses* is a single matching response if result is ``True``, or
      a list of all responses otherwise.

   .. method:: assertResponseMatches(event, regex)

      Assert that :meth:`responseMatches` returns true.

   .. method:: failIfResponseMatches(event, regex)

      The opposite of :meth:`assertResponseMatches`.

   .. method:: assertSucceeds(event)

      Process *event* (either an event or a string to be treated as a
      message from the test user on the test source), and check that it is
      processed by some :class:`Processor <ibid.plugins.Processor>` and no
      complaint is set.

   .. method:: assertFails(event)

      The opposite of :meth:`assertSucceeds`.
