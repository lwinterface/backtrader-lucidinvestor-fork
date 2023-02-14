#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import collections
from copy import copy
from datetime import date, datetime, timedelta
import inspect
import bisect
import itertools
import random
import threading
import time
import logging

from ib.ext.Contract import Contract
import ib.opt as ibopt

from backtrader import TimeFrame, Position
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import bytes, bstr, queue, with_metaclass, long
from backtrader.utils import AutoDict, UTC
from backtrader.brokers import ibbroker

bytes = bstr  # py2/3 need for ibpy


def _ts2dt(tstamp=None):
    # Transforms a RTVolume timestamp to a datetime object
    if not tstamp:
        return datetime.utcnow()

    sec, msec = divmod(long(tstamp), 1000)
    usec = msec * 1000
    return datetime.utcfromtimestamp(sec).replace(microsecond=usec)


class RTVolume(object):
    """Parses a tickString tickType 48 (RTVolume) event from the IB API into its
    constituent fields

    Supports using a "price" to simulate an RTVolume from a tickPrice event
    on 2022.10.11: rtvol = '357.36;8344.0000000000000000;1665499045563;197349.0000000000000000;357.30841548;false'
    """
    _fields = [
        ('price', float),
        ('size', float),
        ('datetime', _ts2dt),
        ('volume', float),
        ('vwap', float),
        ('single', bool)
    ]

    def __init__(self, rtvol='', price=None, tmoffset=None):
        # Use a provided string or simulate a list of empty tokens
        tokens = iter(rtvol.split(';'))

        # Put the tokens as attributes using the corresponding func
        for name, func in self._fields:
            setattr(self, name, func(next(tokens)) if rtvol else func())

        # If price was provided use it
        if price is not None:
            self.price = price

        if tmoffset is not None:
            self.datetime += tmoffset


class BidAsk(object):
    '''Parses a LIVE tickPrice tickType 1 & 2 (Bid & Ask Price) event from the IB API into its
    constituent fields.

    Market data tick price callback. Handles all price related ticks. Every tickPrice callback is followed by a
    tickSize. A tickPrice value of -1 or 0 followed by a tickSize of 0 indicates there is no data for this field
    currently available, whereas a tickPrice with a positive tickSize indicates an active quote of 0 (typically for
    a combo contract).

    '''
    _fields = [
        ('price', float),
        ('datetime', _ts2dt)
    ]

    def __init__(self, price=None, tmoffset=None):
        # Use a provided string or simulate a list of empty tokens
        # tokens = iter(msg.split(';'))

        if price is not None:
            self.price = price

        # If time/offset was provided use it
        # if tmoffset is not None:
        #    self.datetime += tmoffset


class MetaSingleton(MetaParams):
    '''Metaclass to make a metaclassed class a singleton'''

    def __init__(cls, name, bases, dct):
        super(MetaSingleton, cls).__init__(name, bases, dct)
        cls._singleton = None

    def __call__(cls, *args, **kwargs):
        if cls._singleton is None:
            cls._singleton = (
                super(MetaSingleton, cls).__call__(*args, **kwargs))

        return cls._singleton


# Decorator to mark methods to register with ib.opt
def ibregister(f):
    f._ibregister = True
    return f


class IBStore(with_metaclass(MetaSingleton, object)):
    '''Singleton class wrapping an ibpy ibConnection instance.

    The parameters can also be specified in the classes which use this store,
    like ``IBData`` and ``IBBroker``

    Params:

      - ``host`` (default:``127.0.0.1``): where IB TWS or IB Gateway are
        actually running. And although this will usually be the localhost, it
        must not be

      - ``port`` (default: ``7496``): port to connect to. The demo system uses
        ``7497``

      - ``clientId`` (default: ``None``): which clientId to use to connect to
        TWS.

        ``None``: generates a random id between 1 and 65535
        An ``integer``: will be passed as the value to use.

      - ``notifyall`` (default: ``False``)

        If ``False`` only ``error`` messages will be sent to the
        ``notify_store`` methods of ``Cerebro`` and ``Strategy``.

        If ``True``, each and every message received from TWS will be notified

      - ``_debug`` (default: ``False``)

        Print all messages received from TWS to standard output

      - ``reconnect`` (default: ``3``)

        Number of attempts to try to reconnect after the 1st connection attempt
        fails

        Set it to a ``-1`` value to keep on reconnecting forever

      - ``timeout`` (default: ``3.0``)

        Time in seconds between reconnection attemps

      - ``timeoffset`` (default: ``True``)

        If True, the time obtained from ``reqCurrentTime`` (IB Server time)
        will be used to calculate the offset to localtime and this offset will
        be used for the price notifications (tickPrice events, for example for
        CASH markets) to modify the locally calculated timestamp.

        The time offset will propagate to other parts of the ``backtrader``
        ecosystem like the **resampling** to align resampling timestamps using
        the calculated offset.

      - ``timerefresh`` (default: ``60.0``)

        Time in seconds: how often the time offset has to be refreshed

      - ``indcash`` (default: ``True``)

        Manage IND codes as if they were cash for price retrieval
    '''

    # Set a base for the data requests (historical/realtime) to distinguish the
    # id in the error notifications from orders, where the basis (usually
    # starting at 1) is set by TWS
    REQIDBASE = 0x01000000

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    params = (
        ('host', '127.0.0.1'),
        ('port', 7496),
        ('clientId', None),  # None generates a random clientid 1 -> 2^16
        ('notifyall', False),
        ('_debug', False),
        ('reconnect', 3),  # -1 forever, 0 No, > 0 number of retries
        ('timeout', 3.0),  # timeout between reconnections
        ('timeoffset', True),  # Use offset to server for timestamps if needed
        ('timerefresh', 60.0),  # How often to refresh the timeoffset
        ('indcash', True),  # Treat IND codes as CASH elements
    )

    @classmethod
    def getdata(cls, *args, **kwargs):
        '''Returns ``DataCls`` with args, kwargs'''
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        '''Returns broker with *args, **kwargs from registered ``BrokerCls``'''
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self):
        super(IBStore, self).__init__()

        self._lock_q = threading.Lock()  # sync access to _tickerId/Queues
        self._lock_accupd = threading.Lock()  # sync account updates
        self._lock_pos = threading.Lock()  # sync account updates
        self._lock_notif = threading.Lock()  # sync access to notif queue

        # Account list received
        self._event_managed_accounts = threading.Event()
        self._event_accdownload = threading.Event()

        self.dontreconnect = False  # for non-recoverable connect errors

        self._env = None  # reference to cerebro for general notifications
        self.broker = None  # broker instance
        self.datas = list()  # datas that have registered over start
        self.ccount = 0  # requests to start (from cerebro or datas)

        self._lock_tmoffset = threading.Lock()
        self.tmoffset = timedelta()  # to control time difference with server

        self._stream_bidask = False  # capture bid/ask or not
        self._use_initial_tickPrice = False  # do we wait for a proper RTVolume instance to trigger LIVE notification
        self.initial_tickPrice = dict()  # used to notify tickPrice at the tickerID level
        self._init_lastprice = dict()  # used to notify initial last_price used as first data point in price feed at tickerId level

        # Structures to hold datas requests
        self.qs = collections.OrderedDict()  # key: tickerId -> queues
        self.qs_bid = collections.OrderedDict()
        self.qs_ask = collections.OrderedDict()
        self.ts = collections.OrderedDict()  # key: queue -> tickerId
        self.iscash = dict()  # tickerIds from cash products (for ex: EUR.JPY)

        self.histexreq = dict()  # holds segmented historical requests
        self.histfmt = dict()  # holds datetimeformat for request
        self.histsend = dict()  # holds sessionend (data time) for request
        self.histtz = dict()  # holds sessionend (data time) for request

        self.acc_cash = AutoDict()  # current total cash per account
        self.acc_value = AutoDict()  # current total value per account
        self.acc_upds = AutoDict()  # current account valueinfos per account

        self.port_update = False  # indicate whether to signal to broker

        self.positions = collections.defaultdict(Position)  # actual positions
        self.positions_current = dict()

        self._tickerId = itertools.count(self.REQIDBASE)  # unique tickerIds
        self.orderid = None  # next possible orderid (will be itertools.count)

        self.cdetails = collections.defaultdict(list)  # hold cdetails requests

        self.managed_accounts = list()  # received via managedAccounts

        self.notifs = queue.Queue()  # store notifications for cerebro

        # Use the provided clientId or a random one
        if self.p.clientId is None:
            self.clientId = random.randint(1, pow(2, 16) - 1)
        else:
            self.clientId = self.p.clientId

        # ibpy connection object
        self.conn = ibopt.ibConnection(
            host=self.p.host, port=self.p.port, clientId=self.clientId)

        # register a printall method if requested
        if self.p._debug or self.p.notifyall:
            self.conn.registerAll(self.watcher)

        # Register decorated methods with the conn
        methods = inspect.getmembers(self, inspect.ismethod)
        for name, method in methods:
            if not getattr(method, '_ibregister', False):
                continue

            message = getattr(ibopt.message, name)
            # amongst others, tickString & tickPrice is registered here.
            self.conn.register(method, message)

        # This utility key function transforms a barsize into a:
        #   (Timeframe, Compression) tuple which can be sorted
        def keyfn(x):
            n, t = x.split()
            tf, comp = self._sizes[t]
            return (tf, int(n) * comp)

        # This utility key function transforms a duration into a:
        #   (Timeframe, Compression) tuple which can be sorted
        def key2fn(x):
            n, d = x.split()
            tf = self._dur2tf[d]
            return (tf, int(n))

        # Generate a table of reverse durations
        self.revdur = collections.defaultdict(list)
        # The table (dict) is a ONE to MANY relation of
        #   duration -> barsizes
        # Here it is reversed to get a ONE to MANY relation of
        #   barsize -> durations
        for duration, barsizes in self._durations.items():
            for barsize in barsizes:
                self.revdur[keyfn(barsize)].append(duration)

        # Once managed, sort the durations according to real duration and not
        # to the text form using the utility key above
        for barsize in self.revdur:
            self.revdur[barsize].sort(key=key2fn)

    def start(self, data=None, broker=None):
        self.reconnect(fromstart=True)  # reconnect should be an invariant

        # Datas require some processing to kickstart data reception
        if data is not None:
            self._env = data._env
            # For datas simulate a queue with None to kickstart co
            self.datas.append(data)

            # if connection fails, get a fake registration that will force the
            # datas to try to reconnect or else bail out
            return self.getTickerQueue(start=True)

        elif broker is not None:
            self.broker = broker

    def stop(self):
        try:
            self.conn.disconnect()  # disconnect should be an invariant
        except AttributeError:
            pass  # conn may have never been connected and lack "disconnect"

        # Unblock any calls set on these events
        self._event_managed_accounts.set()
        self._event_accdownload.set()

    def logmsg(self, *args):
        # for logging purposes
        if self.p._debug:
            print(*args)

    def watcher(self, msg):
        # will be registered to see all messages if debug is requested
        self.logmsg(str(msg))
        if self.p.notifyall:
            self.notifs.put((msg, tuple(msg.values()), dict(msg.items())))

    def connected(self):
        # The isConnected method is available through __getattr__ indirections
        # and may not be present, which indicates that no connection has been
        # made because the subattribute sender has not yet been created, hence
        # the check for the AttributeError exception
        try:
            return self.conn.isConnected()
        except AttributeError:
            pass

        return False  # non-connected (including non-initialized)

    def reconnect(self, fromstart=False, resub=False):
        # This method must be an invariant in that it can be called several
        # times from the same source and must be consistent. An exampler would
        # be 5 datas which are being received simultaneously and all request a
        # reconnect

        # Policy:
        #  - if dontreconnect has been set, no option to connect is possible
        #  - check connection and use the absence of isConnected as signal of
        #    first ever connection (add 1 to retries too)
        #  - Calculate the retries (forever or not)
        #  - Try to connct
        #  - If achieved and fromstart is false, the datas will be
        #    re-kickstarted to recreate the subscription
        firstconnect = False
        try:
            if self.conn.isConnected():
                if resub:
                    self.startdatas()
                return True  # nothing to do
        except AttributeError:
            # Not connected, several __getattr__ indirections to
            # self.conn.sender.client.isConnected
            firstconnect = True

        if self.dontreconnect:
            return False

        # This is only invoked from the main thread by datas and therefore no
        # lock is needed to control synchronicity to it
        retries = self.p.reconnect
        if retries >= 0:
            retries += firstconnect

        while retries < 0 or retries:
            if not firstconnect:
                time.sleep(self.p.timeout)

            firstconnect = False

            if self.conn.connect():
                if not fromstart or resub:
                    self.startdatas()
                return True  # connection successful

            if retries > 0:
                retries -= 1

        self.dontreconnect = True
        return False  # connection/reconnection failed

    def startdatas(self):
        # kickstrat datas, not returning until all of them have been done
        ts = list()
        for data in self.datas:
            t = threading.Thread(target=data.reqdata)
            t.start()
            #time.sleep(0.1)
            ts.append(t)

        for t in ts:
            t.join()

    def stopdatas(self):
        # stop subs and force datas out of the loop (in LIFO order)
        qs = list(self.qs.values())
        ts = list()
        for data in self.datas:
            t = threading.Thread(target=data.canceldata)
            t.start()
            ts.append(t)

        for t in ts:
            t.join()

        for q in reversed(qs):  # datamaster the last one to get a None
            q.put(None)

    def get_notifications(self):
        '''Return the pending "store" notifications'''
        # The background thread could keep on adding notifications. The None
        # mark allows to identify which is the last notification to deliver
        self.notifs.put(None)  # put a mark
        notifs = list()
        while True:
            notif = self.notifs.get()
            if notif is None:  # mark is reached
                break
            notifs.append(notif)

        return notifs

    @ibregister
    def error(self, msg):
        # 100-199 Order/Data/Historical related
        # 200-203 tickerId and Order Related
        # 300-399 A mix of things: orders, connectivity, tickers, misc errors
        # 400-449 Seem order related again
        # 500-531 Connectivity/Communication Errors
        # 10000-100027 Mix of special orders/routing
        # 1100-1102 TWS connectivy to the outside
        # 1300- Socket dropped in client-TWS communication
        # 2100-2110 Informative about Data Farm status (id=-1)

        # All errors are logged to the environment (cerebro), because many
        # errors in Interactive Brokers are actually informational and many may
        # actually be of interest to the user
        if not self.p.notifyall:
            self.notifs.put((msg, tuple(msg.values()), dict(msg.items())))

        # Manage those events which have to do with connection
        if msg.errorCode is None:
            # Usually received as an error in connection of just before disconn
            pass
        elif msg.errorCode in [200, 203, 162, 320, 321, 322]:
            # cdetails 200 security not found, notify over right queue
            # cdetails 203 security not allowed for acct
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                self.cancelQueue(q, True)

        elif msg.errorCode in [354, 420]:
            # 354 no subscription, 420 no real-time bar for contract
            # the calling data to let the data know ... it cannot resub
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                q.put(-msg.errorCode)
                self.cancelQueue(q)

        elif msg.errorCode == 10225:
            # 10225-Bust event occurred, current subscription is deactivated.
            # Please resubscribe real-time bars immediately.
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                q.put(-msg.errorCode)

        elif msg.errorCode == 326:  # not recoverable, clientId in use
            self.dontreconnect = True
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 502:
            # Cannot connect to TWS: port, config not open, tws off (504 then)
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 504:  # Not Connected for data op
            # Once for each data
            pass  # don't need to manage it

        elif msg.errorCode == 1300:
            # TWS has been closed. The port for a new connection is there
            # newport = int(msg.errorMsg.split('-')[-1])  # bla bla bla -7496
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 1100:
            # Connection lost - Notify ... datas will wait on the queue
            # with no messages arriving
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode == 1101:
            # Connection restored and tickerIds are gone
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode == 1102:
            # Connection restored and tickerIds maintained
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode < 500:
            # Given the myriad of errorCodes, start by assuming is an order
            # error and if not, the checks there will let it go
            if msg.id < self.REQIDBASE:
                if self.broker is not None:
                    self.broker.push_ordererror(msg)
            else:
                # Cancel the queue if a "data" reqId error is given: sanity
                q = self.qs[msg.id]
                self.cancelQueue(q, True)

    @ibregister
    def connectionClosed(self, msg):
        # Sometmes this comes without 1300/502 or any other and will not be
        # seen in error hence the need to manage the situation independently
        self.conn.disconnect()
        self.stopdatas()

    @ibregister
    def managedAccounts(self, msg):
        # 1st message in the stream
        self.managed_accounts = msg.accountsList.split(',')
        self._event_managed_accounts.set()

        # Request time to avoid synchronization issues
        self.reqCurrentTime()

    def reqCurrentTime(self):
        self.conn.reqCurrentTime()

    @ibregister
    def currentTime(self, msg):
        if not self.p.timeoffset:  # only if requested ... apply timeoffset
            return
        curtime = datetime.fromtimestamp(float(msg.time))
        with self._lock_tmoffset:
            self.tmoffset = curtime - datetime.now()

        threading.Timer(self.p.timerefresh, self.reqCurrentTime).start()

    def timeoffset(self):
        with self._lock_tmoffset:
            return self.tmoffset

    def nextTickerId(self):
        # Get the next ticker using next on the itertools.count
        return next(self._tickerId)

    @ibregister
    def nextValidId(self, msg):
        # Create a counter from the TWS notified value to apply to orders
        self.orderid = itertools.count(msg.orderId)

    def nextOrderId(self):
        # Get the next ticker using next on the itertools.count made with the
        # notified value from TWS
        return next(self.orderid)

    def reuseQueue(self, tickerId):
        '''Reuses queue for tickerId, returning the new tickerId and q'''
        with self._lock_q:
            # Invalidate tickerId in qs (where it is a key)
            q = self.qs.pop(tickerId, None)  # invalidate old
            iscash = self.iscash.pop(tickerId, None)

            # Update ts: q -> ticker
            tickerId = self.nextTickerId()  # get new tickerId
            self.ts[q] = tickerId  # Update ts: q -> tickerId
            self.qs[tickerId] = q  # Update qs: tickerId -> q
            self.iscash[tickerId] = iscash

        return tickerId, q

    def getTickerQueue(self, start=False, for_reqdata=False):
        '''Creates ticker/Queue for data delivery to a data feed'''
        q = queue.Queue()
        # Insertion will block once this size has been reached, until queue items are consumed or queue is cleared
        q_bid = queue.Queue(maxsize=100)
        q_ask = queue.Queue(maxsize=100)

        if start:
            q.put(None)
            q_bid.put(None)
            q_ask.put(None)
            return q, q_bid, q_ask

        with self._lock_q:
            tickerId = self.nextTickerId()
            self.qs[tickerId] = q  # can be managed from other thread
            self.ts[q] = tickerId
            self.iscash[tickerId] = False
            self.qs_bid[tickerId] = q_bid
            self.qs_ask[tickerId] = q_ask

            if self._use_initial_tickPrice and for_reqdata:
                self.initial_tickPrice[tickerId] = True
                self._init_lastprice[tickerId] = False

        return tickerId, q, q_bid, q_ask


    def cancelQueue(self, q, sendnone=False):
        '''Cancels a Queue for data delivery'''
        # pop ts (tickers) and with the result qs (queues)
        tickerId = self.ts.pop(q, None)
        self.qs.pop(tickerId, None)
        self.qs_bid.pop(tickerId, None)
        self.qs_ask.pop(tickerId, None)

        self.iscash.pop(tickerId, None)
        self.initial_tickPrice.pop(tickerId, None)

        if sendnone:
            q.put(None)

    def validQueue(self, q):
        '''Returns (bool)  if a queue is still valid'''
        return q in self.ts  # queue -> ticker

    def getContractDetails(self, contract, maxcount=None):
        cds = list()
        q, q_bid, q_ask = self.reqContractDetails(contract)
        while True:
            msg = q.get()
            if msg is None:
                break
            cds.append(msg)

        if not cds or (maxcount and len(cds) > maxcount):
            err = 'Ambiguous contract: none/multiple answers received'
            self.notifs.put((err, cds, {}))
            return None

        return cds

    def reqContractDetails(self, contract):
        # get a ticker/queue for identification/data delivery
        tickerId, q, q_bid, q_ask = self.getTickerQueue()
        self.conn.reqContractDetails(tickerId, contract)
        return q, q_bid, q_ask

    @ibregister
    def contractDetailsEnd(self, msg):
        '''Signal end of contractdetails'''
        self.cancelQueue(self.qs[msg.reqId], True)

    @ibregister
    def contractDetails(self, msg):
        '''Receive answer and pass it to the queue'''
        self.qs[msg.reqId].put(msg)

    def reqHistoricalDataEx(self, contract, enddate, begindate,
                            timeframe, compression,
                            what=None, useRTH=False, tz='', sessionend=None,
                            tickerId=None):
        '''
        Extension of the raw reqHistoricalData proxy, which takes two dates
        rather than a duration, barsize and date

        It uses the IB published valid duration/barsizes to make a mapping and
        spread a historical request over several historical requests if needed
        '''
        # Keep a copy for error reporting purposes
        kwargs = locals().copy()
        kwargs.pop('self', None)  # remove self, no need to report it

        if timeframe < TimeFrame.Seconds:
            # Ticks are not supported
            return self.getTickerQueue(start=True)

        if enddate is None:
            enddate = datetime.now()

        if begindate is None:
            duration = self.getmaxduration(timeframe, compression)
            if duration is None:
                err = ('No duration for historical data request for '
                       'timeframe/compresison')
                self.notifs.put((err, (), kwargs))
                return self.getTickerQueue(start=True)
            barsize = self.tfcomp_to_size(timeframe, compression)
            if barsize is None:
                err = ('No supported barsize for historical data request for '
                       'timeframe/compresison')
                self.notifs.put((err, (), kwargs))
                return self.getTickerQueue(start=True)

            return self.reqHistoricalData(contract=contract, enddate=enddate,
                                          duration=duration, barsize=barsize,
                                          what=what, useRTH=useRTH, tz=tz,
                                          sessionend=sessionend)

        # Check if the requested timeframe/compression is supported by IB
        durations = self.getdurations(timeframe, compression)
        if not durations:  # return a queue and put a None in it
            return self.getTickerQueue(start=True)

        # Get or reuse a queue
        if tickerId is None:
            tickerId, q = self.getTickerQueue()
        else:
            tickerId, q = self.reuseQueue(tickerId)  # reuse q for old tickerId

        # Get the best possible duration to reduce number of requests
        duration = None
        for dur in durations:
            intdate = self.dt_plus_duration(begindate, dur)
            if intdate >= enddate:
                intdate = enddate
                duration = dur  # begin -> end fits in single request
                break

        if duration is None:  # no duration large enough to fit the request
            duration = durations[-1]

            # Store the calculated data
            self.histexreq[tickerId] = dict(
                contract=contract, enddate=enddate, begindate=intdate,
                timeframe=timeframe, compression=compression,
                what=what, useRTH=useRTH, tz=tz, sessionend=sessionend)

        barsize = self.tfcomp_to_size(timeframe, compression)
        self.histfmt[tickerId] = timeframe >= TimeFrame.Days
        self.histsend[tickerId] = sessionend
        self.histtz[tickerId] = tz

        if contract.m_secType in ['CASH', 'CFD']:
            self.iscash[tickerId] = 1  # msg.field code
            if not what:
                what = 'BID'  # default for cash unless otherwise specified

        elif contract.m_secType in ['IND'] and self.p.indcash:
            self.iscash[tickerId] = 4  # msg.field code

        what = what or 'TRADES'

        self.conn.reqHistoricalData(
            tickerId,
            contract,
            bytes(intdate.strftime('%Y%m%d %H:%M:%S') + ' GMT'),
            bytes(duration),
            bytes(barsize),
            bytes(what),
            int(useRTH),
            2)  # dateformat 1 for string, 2 for unix time in seconds

        return q

    def reqHistoricalData(self, contract, enddate, duration, barsize,
                          what=None, useRTH=False, tz='', sessionend=None):
        '''Proxy to reqHistorical Data'''

        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()

        if contract.m_secType in ['CASH', 'CFD']:
            self.iscash[tickerId] = True
            if not what:
                what = 'BID'  # TRADES doesn't work
            elif what == 'ASK':
                self.iscash[tickerId] = 2
        else:
            what = what or 'TRADES'

        # split barsize "x time", look in sizes for (tf, comp) get tf
        tframe = self._sizes[barsize.split()[1]][0]
        self.histfmt[tickerId] = tframe >= TimeFrame.Days
        self.histsend[tickerId] = sessionend
        self.histtz[tickerId] = tz

        self.conn.reqHistoricalData(
            tickerId,
            contract,
            bytes(enddate.strftime('%Y%m%d %H:%M:%S') + ' GMT'),
            bytes(duration),
            bytes(barsize),
            bytes(what),
            int(useRTH),
            2)

        return q

    def cancelHistoricalData(self, q):
        '''Cancels an existing HistoricalData request

        Params:
          - q: the Queue returned by reqMktData
        '''
        with self._lock_q:
            self.conn.cancelHistoricalData(self.ts[q])
            self.cancelQueue(q, True)

    def stream_bidask_stop(self):
        '''Activate the queuing of bid/ask streams
           bid/ask cannot be used in conjunction with realtimeBar (no bid/ask provided)
        :param state: boolean set to False by default to align with backtrader default
        :param stream: (str) 'ask' or 'bid'
        :param tickerId:
        :return: None
        '''

        if  self._stream_bidask:
            self._stream_bidask = False

            for q_ticker in self.qs_bid:
                self.qs_bid[q_ticker].queue.clear()
            for q_ticker in self.qs_ask:
                self.qs_ask[q_ticker].queue.clear()

        return

    def stream_bidask_isactive(self):
        return self._stream_bidask

    def reqRealTimeBars(self, contract, useRTH=False, duration=5):
        '''Requests real time bars. Currently, only 5 seconds bars are provided. This request is subject to the same
        pacing as any historical data request: no more than 60 API queries in more than 600 seconds.
        Real time bars subscriptions are also included in the calculation of the number of Level 1 market data
        subscriptions allowed in an account.

        Creates a request for (5 seconds) Real Time Bars

        NOT VALID FOR STREAMING BID/ASK prices

        Params:
          - contract: a ib.ext.Contract.Contract intance
          - useRTH: (default: False) passed to TWS - useRTH	set to 0 to obtain the data which was also generated
          outside of the Regular Trading Hours, set to 1 to obtain only the RTH data
          - duration: (default: 5) passed to TWS, no other value works in 2016)

        Returns:
          - a Queue the client can wait on to receive a RTVolume instance
        '''
        # get a ticker/queue for identification/data delivery
        tickerId, q, q_bid, q_ask = self.getTickerQueue(for_reqdata=True)

        # 20150929 - Only 5 secs supported for duration
        # whatToShow	the nature of the data being retrieved:
        #
        #     TRADES <- DEFAULT IN BACKTRADER
        #     MIDPOINT
        #     BID
        #     ASK
        self.conn.reqRealTimeBars(
            tickerId,
            contract,
            duration,
            bytes('TRADES'),
            int(useRTH))

        return q, {'tickerId': tickerId, 'queue': q_bid}, {'tickerId': tickerId, 'queue': q_ask}

    def cancelRealTimeBars(self, q):
        '''Cancels an existing MarketData subscription

        Params:
          - q: the Queue returned by reqMktData
        '''
        with self._lock_q:
            tickerId = self.ts.get(q, None)
            if tickerId is not None:
                self.conn.cancelRealTimeBars(tickerId)

            self.cancelQueue(q, True)

    def reqMktData(self, contract, initial_tickPrice=False, bidask=False, what=None):
        ''' Requests real time market data. Returns market data for an instrument either in real time or 10-15 minutes
        delayed (depending on the market data type specified)

        Creates a MarketData subscription

        Params:
          - contract: a ib.ext.Contract.Contract intance
          - bidask: whether or not bidask is streamed

        Returns:
          - a Queue the client can wait on to receive a RTVolume instance
        '''

        self._stream_bidask = bidask
        self._use_initial_tickPrice = initial_tickPrice

        # get a ticker/queue for identification/data delivery
        # the bid/ask price is part of the default dataset returned
        tickerId, q, q_bid, q_ask = self.getTickerQueue(for_reqdata=True)

        # genericTickList	comma separated ids of the available generic ticks:
        #     100 Option Volume (currently for stocks)
        #     101 Option Open Interest (currently for stocks)
        #     104 Historical Volatility (currently for stocks)
        #     105 Average Option Volume (currently for stocks)
        #     106 Option Implied Volatility (currently for stocks)
        #     162 Index Future Premium
        #     165 Miscellaneous Stats
        #     221 Mark Price (used in TWS P&L computations)
        #     225 Auction values (volume, price and imbalance)
        #     233 RTVolume - contains the last trade price, last trade size, last trade time, total volume, VWAP,
        #                    and single trade flag.
        #     236 Shortable
        #     256 Inventory
        #     258 Fundamental Ratios
        #     411 Realtime Historical Volatility
        #     456 IBDividends
        ticks = '233'  # request RTVOLUME tick delivered over tickString

        if contract.m_secType in ['CASH', 'CFD']:
            self.iscash[tickerId] = True
            # The tickType, left empty in this example, allows you to specify what kind of data you’re looking for.
            # Since the bid/ask price is part of the default dataset returned, we don’t need to specify a tickType.
            ticks = ''  # cash markets do not get RTVOLUME
            if what == 'ASK':
                self.iscash[tickerId] = 2

        # q.put(None)  # to kickstart backfilling
        # Can request 233 also for cash ... nothing will arrive

        # The fourth parameter under reqMktData is if you want snapshot data for an asset that you do not have a
        # subscription to. If you have a market data subscription, or one is not required, set this to False.
        #
        # The fifth item is to obtain a snapshot rather than streaming data. This is for assets you already have a
        # subscription for, or if a subscription is not required.

        # todo: I think we should add 1 False at the end for "subscribed snapshot"
        self.conn.reqMktData(tickerId, contract, bytes(ticks), False)
        # sometimes we are missing the initial connection data (after successful reqMktData connection.
        # Probable cause: # TWS API's inherent limitation of 50 messages per second
        # (also implies a maximum of 50 orders per second being sent to the TWS)
        # https://interactivebrokers.github.io/tws-api/order_limitations.html

        # todo: Ideally we should be able to do it without sleep - but I did not find a more elegant manner - I did not
        # found what should be listened/checked.
        time.sleep(0.25)  # Time in seconds

        # The market data is then delivered, depending on the tick type selected via tickPrice (bid/ask), tickSize,
        # tickString (last close) or tickGeneric.
        return q, {'tickerId': tickerId, 'queue': q_bid}, {'tickerId': tickerId, 'queue': q_ask}

    def cancelMktData(self, q):
        '''Cancels an existing MarketData subscription

        Params:
          - q: the Queue returned by reqMktData
        '''
        with self._lock_q:
            tickerId = self.ts.get(q, None)
            if tickerId is not None:
                self.conn.cancelMktData(tickerId)

            self.cancelQueue(q, True)

    @ibregister
    def tickString(self, msg):
        # Receive and process a tickString message
        #print('String' + str(msg))

        if msg.tickType == 48:  # RTVolume
            # https://interactivebrokers.github.io/tws-api/tick_types.html#rt_volume
            # The RT Volume tick type corresponds to the TWS' Time & Sales window and contains the last trade's price,
            # size and time along with current day's total traded volume, Volume Weighted Average Price (VWAP) and
            # whether or not the trade was filled by a single market maker.

            # https://www.interactivebrokers.com/en/software/tws/usersguidebook/mosaic/timensales.htm
            # There is a new setting available starting in TWS v969 which displays tick-by-tick data in the TWS Time &
            # Sales Window. If this setting is checked, it will provide a higher granularity of data than RTVolume.
            # print('String' + str(msg))

            try:
                rtvol = RTVolume(msg.value)
            except ValueError:  # price not in message ...
                pass
            else:
                # Don't need to adjust the time, because it is in "timestamp"
                # form in the message
                self.qs[msg.tickerId].put(rtvol)

                if self._use_initial_tickPrice and self.initial_tickPrice[msg.tickerId] and self._init_lastprice[msg.tickerId]:

                    # if tickPrice came in first, then len() would be 2, but if tickString came first, then len() is 1.
                    # if len() is 1, no action, the stream is already consistent (did not use tickPrice partial info)
                    if len(self.qs[msg.tickerId].queue) == 2:
                        # remove the initial last_price (without size, vwap ...) for consistency guarantee
                        self.qs[msg.tickerId].get()
                    # stop any other manipulation on self.qs[msg.tickerId]
                    self.initial_tickPrice[msg.tickerId] = False
                    self._init_lastprice[msg.tickerId] = False

    @ibregister
    def tickPrice(self, msg):
        '''
        https://interactivebrokers.github.io/tws-api/interfaceIBApi_1_1EWrapper.html#ae851ec3a1e0fa2d0964c7779b0c89718
        Market data tick price callback. Handles all price related ticks. Every tickPrice callback is followed by a
        tickSize. A tickPrice value of -1 or 0 followed by a tickSize of 0 indicates there is no data for this field
        currently available, whereas a tickPrice with a positive tickSize indicates an active quote of 0 (typically
        for a combo contract).

        Cash Markets have no notion of "last_price"/"last_size" and the
        tracking of the price is done (industry de-facto standard at least with
        the IB API) following the BID price

        Whenever a certain property changes, a new tick event will be triggered. BUT if bid and ask remains, and
        only size is changing, only size will be updated and nothing else will be streamed (i.e. NO tickPrice emitted).
        -> some stocks (like GSY invesco ultra short used for testing) would have a very low bid/ask price movement,
        and thus would not trigger tickPrice or RTVolume quickly and would delay LIVE NOTIFICATION.
        -> considering backtrader is using RTVolume a consistent cross-market interface, we temporarily use a
        RTVolume instance with last_price information only, put it into the client's queue, then replace using the next
        valid RTVolume emitted as tickString (below)
        '''

        #print('TickPrice' + str(msg))
        # Used for "CASH" markets
        # The price field has been seen to be missing in some instances even if "field" is 1
        tickerId = msg.tickerId
        fieldcode = self.iscash[tickerId]

        try:
            if msg.price <= 0:
                print("no data currently available. Most commonly this occurs when requesting data from markets that "
                      "are closed. It can also occur for infrequently trading instruments which do not have open bids "
                      "or offers at that time of the request. "
                      "REF https://interactivebrokers.github.io/tws-api/md_receive.html")
                return

        except ValueError as e:  # price not in message ...
            logging.error('[tickPrice] price not in message ... ' + str(e))
            return

        # if self._stream_bidask or not len(self.qs[tickerId].queue):
        if self._stream_bidask:
            # after a successful reqMrkData, msg.field 1, 2, 4 will be sent for last quotes on bid, ask, price
            # we will use these to populate the Queue for them to be of size at least 1, to prevent waiting for
            # illiquid stocks.
            #
            # specifically, msg.field=4 will populate not len(self.qs[tickerId].queue) and trigger a LIVE notification.

            if msg.field == 2:
                # Lowest price offer on the contract.
                # Tick Id = 2: https://interactivebrokers.github.io/tws-api/tick_types.html
                # print("Ask Price: " + str(msg))
                bidask = BidAsk(price=msg.price)
                self.qs_ask[tickerId].put(bidask)

                if self.qs_ask[tickerId].full():
                    for i in range(int(self.qs_ask[tickerId].maxsize / 2)):
                        self.qs_ask[tickerId].get()

            elif msg.field == 1:
                # Highest priced bid for the contract.
                # Tick Id = 1: https://interactivebrokers.github.io/tws-api/tick_types.html
                # print("Bid Price: " + str(msg))
                bidask = BidAsk(price=msg.price)
                self.qs_bid[tickerId].put(bidask)

                if self.qs_bid[tickerId].full():
                    for i in range(int(self.qs_bid[tickerId].maxsize / 2)):
                        self.qs_bid[tickerId].get()

        # USE LAST_TRADE PRICE DELIVERED UPON SUCCESSFUL reqMarketData CONNECTION to trigger LIVE NOTIFICATION
        if msg.field == 4 and self._use_initial_tickPrice and self.initial_tickPrice[msg.tickerId] and not self._init_lastprice[msg.tickerId]:
            # Last Price: Last price at which the contract traded (does not include some trades in RTVolume).
            # print("Last Price: " + str(msg))
            fakertvol = RTVolume(price=msg.price, tmoffset=self.tmoffset)
            self.qs[msg.tickerId].put(fakertvol)
            self._init_lastprice[msg.tickerId] = True  # <- done once upon successful reqMarketData

        if fieldcode:
            if msg.field == fieldcode:  # Expected cash field code
                try:
                    if msg.price <= 0:
                        # seems to indicate the stream is halted for example in
                        # between 23:00 - 23:15 CET for FOREX
                        return
                except AttributeError:
                    pass

                try:
                    rtvol = RTVolume(price=msg.price, tmoffset=self.tmoffset)
                    # print('rtvol with datetime:', rtvol.datetime)
                except ValueError:  # price not in message ...
                    pass
                else:
                    self.qs[tickerId].put(rtvol)

    @ibregister
    def tickSize(self, msg):
        '''
        Whenever a certain property changes, a new tick event will be triggered. So if bid and ask remains, and
        only size is changing, only size will be updated and nothing else will be streamed.
        :param msg:
        :return:
        '''
        if not self._stream_bidask:
            return

        # https: // interactivebrokers.github.io / tws - api / tick_types.html
        if msg.field == 0:
            # Bid Size
            #print("Bid Size: " + str(msg))
            pass
        elif msg.field == 3:
            # Ask Size
            #print("Ask Size: " + str(msg))
            pass
        return

    @ibregister
    def realtimeBar(self, msg):
        '''Receives x seconds Real Time Bars (at the time of writing only 5
        seconds are supported)

        msg: <realtimeBar reqId=16777217, time=1665600380, open=358.58, high=358.61, low=358.57, close=358.57,
        volume=15, wap=358.59, count=8>

        Not valid for cash markets
        Not valid for BID/ASK quotes
        '''
        # Get a naive localtime object
        msg.time = datetime.utcfromtimestamp(float(msg.time))
        self.qs[msg.reqId].put(msg)

    @ibregister
    def historicalData(self, msg):
        '''Receives the events of a historical data request'''
        # For multi-tiered downloads we'd need to rebind the queue to a new
        # tickerId (in case tickerIds are not reusable) and instead of putting
        # None, issue a new reqHistData with the new data and move formward
        tickerId = msg.reqId
        q = self.qs[tickerId]
        if msg.date.startswith('finished-'):
            self.histfmt.pop(tickerId, None)
            self.histsend.pop(tickerId, None)
            self.histtz.pop(tickerId, None)
            kargs = self.histexreq.pop(tickerId, None)
            if kargs is not None:
                self.reqHistoricalDataEx(tickerId=tickerId, **kargs)
                return

            msg.date = None
            self.cancelQueue(q)
        else:
            dtstr = msg.date  # Format when string req: YYYYMMDD[  HH:MM:SS]
            if self.histfmt[tickerId]:
                sessionend = self.histsend[tickerId]
                dt = datetime.strptime(dtstr, '%Y%m%d')
                dteos = datetime.combine(dt, sessionend)
                tz = self.histtz[tickerId]
                if tz:
                    dteostz = tz.localize(dteos)
                    dteosutc = dteostz.astimezone(UTC).replace(tzinfo=None)
                    # When requesting for example daily bars, the current day
                    # will be returned with the already happened data. If the
                    # session end were added, the new ticks wouldn't make it
                    # through, because they happen before the end of time
                else:
                    dteosutc = dteos

                if dteosutc <= datetime.utcnow():
                    dt = dteosutc

                msg.date = dt
            else:
                msg.date = datetime.utcfromtimestamp(long(dtstr))

        q.put(msg)

    # The _durations are meant to calculate the needed historical data to
    # perform backfilling at the start of a connetion or a connection is lost.
    # Using a timedelta as a key allows to quickly find out which bar size
    # bar size (values in the tuples int the dict) can be used.

    _durations = dict([
        # 60 seconds - 1 min
        ('60 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min')),

        # 120 seconds - 2 mins
        ('120 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins')),

        # 180 seconds - 3 mins
        ('180 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins')),

        # 300 seconds - 5 mins
        ('300 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins')),

        # 600 seconds - 10 mins
        ('600 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins')),

        # 900 seconds - 15 mins
        ('900 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins')),

        # 1200 seconds - 20 mins
        ('1200 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins')),

        # 1800 seconds - 30 mins
        ('1800 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins')),

        # 3600 seconds - 1 hour
        ('3600 S',
         ('5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour')),

        # 7200 seconds - 2 hours
        ('7200 S',
         ('5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours')),

        # 10800 seconds - 3 hours
        ('10800 S',
         ('10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours')),

        # 14400 seconds - 4 hours
        ('14400 S',
         ('15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours')),

        # 28800 seconds - 8 hours
        ('28800 S',
         ('30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours')),

        # 1 days
        ('1 D',
         ('1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day')),

        # 2 days
        ('2 D',
         ('2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day')),

        # 1 weeks
        ('1 W',
         ('3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day', '1 W')),

        # 2 weeks
        ('2 W',
         ('15 mins', '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day', '1 W')),

        # 1 months
        ('1 M',
         ('30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day', '1 W', '1 M')),

        # 2+ months
        ('2 M', ('1 day', '1 W', '1 M')),
        ('3 M', ('1 day', '1 W', '1 M')),
        ('4 M', ('1 day', '1 W', '1 M')),
        ('5 M', ('1 day', '1 W', '1 M')),
        ('6 M', ('1 day', '1 W', '1 M')),
        ('7 M', ('1 day', '1 W', '1 M')),
        ('8 M', ('1 day', '1 W', '1 M')),
        ('9 M', ('1 day', '1 W', '1 M')),
        ('10 M', ('1 day', '1 W', '1 M')),
        ('11 M', ('1 day', '1 W', '1 M')),

        # 1+ years
        ('1 Y', ('1 day', '1 W', '1 M')),
    ])

    # Sizes allow for quick translation from bar sizes above to actual
    # timeframes to make a comparison with the actual data
    _sizes = {
        'secs': (TimeFrame.Seconds, 1),
        'min': (TimeFrame.Minutes, 1),
        'mins': (TimeFrame.Minutes, 1),
        'hour': (TimeFrame.Minutes, 60),
        'hours': (TimeFrame.Minutes, 60),
        'day': (TimeFrame.Days, 1),
        'W': (TimeFrame.Weeks, 1),
        'M': (TimeFrame.Months, 1),
    }

    _dur2tf = {
        'S': TimeFrame.Seconds,
        'D': TimeFrame.Days,
        'W': TimeFrame.Weeks,
        'M': TimeFrame.Months,
        'Y': TimeFrame.Years,
    }

    def getdurations(self, timeframe, compression):
        key = (timeframe, compression)
        if key not in self.revdur:
            return []

        return self.revdur[key]

    def getmaxduration(self, timeframe, compression):
        key = (timeframe, compression)
        try:
            return self.revdur[key][-1]
        except (KeyError, IndexError):
            pass

        return None

    def tfcomp_to_size(self, timeframe, compression):
        if timeframe == TimeFrame.Months:
            return '{} M'.format(compression)

        if timeframe == TimeFrame.Weeks:
            return '{} W'.format(compression)

        if timeframe == TimeFrame.Days:
            if not compression % 7:
                return '{} W'.format(compression // 7)

            return '{} day'.format(compression)

        if timeframe == TimeFrame.Minutes:
            if not compression % 60:
                hours = compression // 60
                return ('{} hour'.format(hours)) + ('s' * (hours > 1))

            return ('{} min'.format(compression)) + ('s' * (compression > 1))

        if timeframe == TimeFrame.Seconds:
            return '{} secs'.format(compression)

        # Microseconds or ticks
        return None

    def dt_plus_duration(self, dt, duration):
        size, dim = duration.split()
        size = int(size)
        if dim == 'S':
            return dt + timedelta(seconds=size)

        if dim == 'D':
            return dt + timedelta(days=size)

        if dim == 'W':
            return dt + timedelta(days=size * 7)

        if dim == 'M':
            month = dt.month - 1 + size  # -1 to make it 0 based, readd below
            years, month = divmod(month, 12)
            return dt.replace(year=dt.year + years, month=month + 1)

        if dim == 'Y':
            return dt.replace(year=dt.year + size)

        return dt  # could do nothing with it ... return it intact

    def calcdurations(self, dtbegin, dtend):
        '''Calculate a duration in between 2 datetimes'''
        duration = self.histduration(dtbegin, dtend)

        if duration[-1] == 'M':
            m = int(duration.split()[0])
            m1 = min(2, m)  # (2, 1) -> 1, (2, 7) -> 2. Bottomline: 1 or 2
            m2 = max(1, m1)  # m1 can only be 1 or 2
            checkdur = '{} M'.format(m2)
        elif duration[-1] == 'Y':
            checkdur = '1 Y'
        else:
            checkdur = duration

        sizes = self._durations[checkdur]
        return duration, sizes

    def calcduration(self, dtbegin, dtend):
        '''Calculate a duration in between 2 datetimes. Returns single size'''
        duration, sizes = self._calcdurations(dtbegin, dtend)
        return duration, sizes[0]

    def histduration(self, dt1, dt2):
        # Given two dates calculates the smallest possible duration according
        # to the table from the Historical Data API limitations provided by IB
        #
        # Seconds: 'x S' (x: [60, 120, 180, 300, 600, 900, 1200, 1800, 3600,
        #                     7200, 10800, 14400, 28800])
        # Days: 'x D' (x: [1, 2]
        # Weeks: 'x W' (x: [1, 2])
        # Months: 'x M' (x: [1, 11])
        # Years: 'x Y' (x: [1])

        td = dt2 - dt1  # get a timedelta for calculations

        # First: array of secs
        tsecs = td.total_seconds()
        secs = [60, 120, 180, 300, 600, 900, 1200, 1800, 3600, 7200, 10800,
                14400, 28800]

        idxsec = bisect.bisect_left(secs, tsecs)
        if idxsec < len(secs):
            return '{} S'.format(secs[idxsec])

        tdextra = bool(td.seconds or td.microseconds)  # over days/weeks

        # Next: 1 or 2 days
        days = td.days + tdextra
        if td.days <= 2:
            return '{} D'.format(days)

        # Next: 1 or 2 weeks
        weeks, d = divmod(td.days, 7)
        weeks += bool(d or tdextra)
        if weeks <= 2:
            return '{} W'.format(weeks)

        # Get references to dt components
        y2, m2, d2 = dt2.year, dt2.month, dt2.day
        y1, m1, d1 = dt1.year, dt1.month, dt2.day

        H2, M2, S2, US2 = dt2.hour, dt2.minute, dt2.second, dt2.microsecond
        H1, M1, S1, US1 = dt1.hour, dt1.minute, dt1.second, dt1.microsecond

        # Next: 1 -> 11 months (11 incl)
        months = (y2 * 12 + m2) - (y1 * 12 + m1) + (
                (d2, H2, M2, S2, US2) > (d1, H1, M1, S1, US1))
        if months <= 1:  # months <= 11
            return '1 M'  # return '{} M'.format(months)
        elif months <= 11:
            return '2 M'  # cap at 2 months to keep the table clean

        # Next: years
        # y = y2 - y1 + (m2, d2, H2, M2, S2, US2) > (m1, d1, H1, M1, S1, US1)
        # return '{} Y'.format(y)

        return '1 Y'  # to keep the table clean

    def makecontract(self, symbol, sectype, exch, curr,
                     expiry='', strike=0.0, right='', mult=1):
        '''returns a contract from the parameters without check'''

        contract = Contract()
        contract.m_symbol = bytes(symbol)
        contract.m_secType = bytes(sectype)
        contract.m_exchange = bytes(exch)
        if curr:
            contract.m_currency = bytes(curr)
        if sectype in ['FUT', 'OPT', 'FOP']:
            contract.m_expiry = bytes(expiry)
        if sectype in ['OPT', 'FOP']:
            contract.m_strike = strike
            contract.m_right = bytes(right)
        if mult:
            contract.m_multiplier = bytes(mult)
        return contract

    def cancelOrder(self, orderid):
        '''Proxy to cancelOrder'''
        self.conn.cancelOrder(orderid)

    def placeOrder(self, orderid, contract, order):
        '''Proxy to placeOrder'''
        self.conn.placeOrder(orderid, contract, order)

    @ibregister
    def openOrder(self, msg):
        '''Receive the event ``openOrder`` events'''
        self.broker.push_orderstate(msg)

    @ibregister
    def execDetails(self, msg):
        '''Receive execDetails'''
        self.broker.push_execution(msg.execution)

    @ibregister
    def orderStatus(self, msg):
        '''Receive the event ``orderStatus``'''
        self.broker.push_orderstatus(msg)

    @ibregister
    def commissionReport(self, msg):
        '''Receive the event commissionReport'''
        self.broker.push_commissionreport(msg.commissionReport)

    def reqPositions(self):
        '''Proxy to reqPositions'''
        self.conn.reqPositions()

    @ibregister
    def position(self, msg):
        '''Receive event positions'''
        pass  # Not implemented yet

    def reqAccountUpdates(self, subscribe=True, account=None):
        '''Proxy to reqAccountUpdates

        If ``account`` is ``None``, wait for the ``managedAccounts`` message to
        set the account codes
        '''
        if account is None:
            self._event_managed_accounts.wait()
            account = self.managed_accounts[0]

        self.conn.reqAccountUpdates(subscribe, bytes(account))

    @ibregister
    def accountDownloadEnd(self, msg):
        # Signals the end of an account update
        # the event indicates it's over. It's only false once, and can be used
        # to find out if it has at least been downloaded once
        self._event_accdownload.set()
        if False:
            if self.port_update:
                if isinstance(self.broker, ibbroker.IBBroker):
                    self.broker.push_portupdate()

                self.port_update = False

    @ibregister
    def updatePortfolio(self, msg):
        # Lock access to the position dicts. This is called in sub-thread and
        # can kick in at any time
        with self._lock_pos:
            if not self._event_accdownload.is_set():  # 1st event seen
                position = Position(msg.position, msg.averageCost)
                self.positions[msg.contract.m_conId] = position
                self.cdetails[msg.contract.m_conId] = msg.contract
            else:
                position = self.positions[msg.contract.m_conId]
                if not position.fix(msg.position, msg.averageCost):
                    err = ('The current calculated position and '
                           'the position reported by the broker do not match. '
                           'Operation can continue, but the trades '
                           'calculated in the strategy may be wrong')

                    self.notifs.put((err, (), {}))

                # Flag signal to broker at the end of account download
                # self.port_update = True
                if isinstance(self.broker, ibbroker.IBBroker):
                    self.broker.push_portupdate()

    def getposition(self, contract, clone=False):
        # Lock access to the position dicts. This is called from main thread
        # and updates could be happening in the background
        with self._lock_pos:
            position = self.positions[contract.m_conId]
            if clone:
                return copy(position)

            return position

    @ibregister
    def updateAccountValue(self, msg):
        # Lock access to the dicts where values are updated. This happens in a
        # sub-thread and could kick it at anytime
        with self._lock_accupd:
            try:
                value = float(msg.value)
            except ValueError:
                value = msg.value

            self.acc_upds[msg.accountName][msg.key][msg.currency] = value

            if msg.key == 'NetLiquidation':
                # NetLiquidationByCurrency and currency == 'BASE' is the same
                self.acc_value[msg.accountName] = value
            elif msg.key == 'TotalCashBalance' and msg.currency == 'BASE':
                self.acc_cash[msg.accountName] = value

    def get_acc_values(self, account=None):
        '''Returns all account value infos sent by TWS during regular updates
        Waits for at least 1 successful download

        If ``account`` is ``None`` then a dictionary with accounts as keys will
        be returned containing all accounts

        If account is specified or the system has only 1 account the dictionary
        corresponding to that account is returned
        '''
        # Wait for at least 1 account update download to have been finished
        # before the account infos can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._updacclock:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return self.acc_upds.copy()

                elif len(self.managed_accounts) > 1:
                    return self.acc_upds.copy()

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_upds[account].copy()
            except KeyError:
                pass

            return self.acc_upds.copy()

    def get_acc_value(self, account=None):
        '''Returns the net liquidation value sent by TWS during regular updates
        Waits for at least 1 successful download

        If ``account`` is ``None`` then a dictionary with accounts as keys will
        be returned containing all accounts

        If account is specified or the system has only 1 account the dictionary
        corresponding to that account is returned
        '''
        # Wait for at least 1 account update download to have been finished
        # before the value can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._lock_accupd:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return float()

                elif len(self.managed_accounts) > 1:
                    return sum(self.acc_value.values())

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_value[account]
            except KeyError:
                pass

            return float()

    def get_acc_cash(self, account=None):
        '''Returns the total cash value sent by TWS during regular updates
        Waits for at least 1 successful download

        If ``account`` is ``None`` then a dictionary with accounts as keys will
        be returned containing all accounts

        If account is specified or the system has only 1 account the dictionary
        corresponding to that account is returned
        '''
        # Wait for at least 1 account update download to have been finished
        # before the cash can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._lock_accupd:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return float()

                elif len(self.managed_accounts) > 1:
                    return sum(self.acc_cash.values())

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_cash[account]
            except KeyError:
                pass
