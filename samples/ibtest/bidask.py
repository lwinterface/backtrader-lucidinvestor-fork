#!/usr/bin/env python

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import backtrader as bt
from datetime import datetime
import pytz as tz


class St(bt.Strategy):

    def __init__(self):
        # nb of next_live run before clean shutdown
        self.runtime = 10

    def prenext(self):
        '''
        hook to let developers access things before the following guarantee can be met:
            - guarantee: all buffers (indicators, data feeds) can deliver at least data point
            - alternative: see https://www.backtrader.com/blog/2019-05-20-momentum-strategy/momentum-strategy/
        :return:
        '''
        pass

    def next(self):

        if self.data_live:
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("\n\n Current Time =", current_time)

            for asset in self.getdatanames():
                print("\n ASSET: " + str(asset))

                q = self.datas[self.getdatanames().index(asset)].qlive.queue
                print(str(asset) + "/ Close price: " + str(self.datas[self.getdatanames().index(asset)].close[0]))
                print(str(asset) + "/ len qlive: " + str(len(q)))
                try:
                    print("\n" + str(asset) + ": price - " + str(q[-1].price))
                    print(str(asset) + ": vwap - " + str(q[-1].vwap))
                except Exception as e:
                    print(e)
                    print(q)

                try:
                    ask = self.datas[self.getdatanames().index(asset)].asklive['queue'].queue[-1].price
                    bid = self.datas[self.getdatanames().index(asset)].bidlive['queue'].queue[-1].price
                    print(" last ask price is: " + str(float(ask)) + " last bid price is: " + str(float(bid)))
                    print(" len ask: " + str(len(self.datas[self.getdatanames().index(asset)].asklive['queue'].queue)))
                    print(" len bid: " + str(len(self.datas[self.getdatanames().index(asset)].bidlive['queue'].queue)))

                    if self.runtime < 5:
                        # clear bid/ask stream and stop queueing
                        print("STOP BID/ASK - clear bid/ask stream and stop queueing.")
                        self.broker.ib.stream_bidask_stop()

                except Exception as e:
                    print(e)
                    print("error requesting bid/ask price")

            self.runtime = self.runtime - 1

            if self.runtime < 1:
                self.env.runstop()

    data_live = False

    def notify_data(self, data, status, *args, **kwargs):
        print('*' * 5, 'DATA NOTIF:', data._getstatusname(status), *args)

        if status == data.LIVE:
            self.data_live = True


def run(args=None):
    tz_default = tz.timezone('America/New_York')

    datakwargs = dict(
        backfill_start=False,
        backfill=False,
        timeframe=bt.TimeFrame.Ticks,
        bidask=True,
        initial_tickPrice=True,
        rtbar=False,  # if set to True no bid/ask
        tz=tz_default,
        latethrough=False,
        _debug=False
    )

    rekwargs = dict(
        timeframe=bt.TimeFrame.Seconds, compression=10
    )

    cerebro = bt.Cerebro(stdstats=False)
    store = bt.stores.IBStore(port=4001)
    # this lines does the magic of switching from broker simulation, to live trading on IB
    cerebro.broker = store.getbroker()

    ib_name = '-STK-SMART-USD'
    assets = ['GSY']

    for symbol in assets:
        # TODO: Multiple Timeframe Datas can be used in backtrader with no special objects or tweaking: just add the smaller timeframes first.
        # https://www.backtrader.com/docu/data-multitimeframe/data-multitimeframe.html

        # Create the Data Feed for Cerebro
        ib_symbol = symbol + ib_name
        print(" Registering dataname: " + ib_symbol)
        data = store.getdata(dataname=ib_symbol, **datakwargs)
        cerebro.resampledata(data, name=symbol, **rekwargs)

    cerebro.addstrategy(St)
    cerebro.run()


if __name__ == '__main__':
    run()
