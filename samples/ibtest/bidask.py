#!/usr/bin/env python

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import backtrader as bt


# https://medium.com/@danjrod/interactive-brokers-in-python-with-backtrader-23dea376b2fc
# Very quickly a whooping total of 1082 bars. This is so, because backtrader has done back-filling for us.
# only after 1081 bars is the system in a position to provide you with real-time data.
# Remember we are using 10-seconds bars. When we get bar 1082, this is the summary of the last 10 seconds.

class St(bt.Strategy):

    def next(self):
        if self.data_live == True:
            asset = self.getdatanames()[0]

            q = self.datas[self.getdatanames().index(asset)].qlive.queue
            print(str(asset) + "/ Close price: " + str(self.datas[self.getdatanames().index(asset)].close[0]))
            print(str(asset)+ "/ len qlive: " +str(len(q)))
            try:
                print("\n"+ str(asset) +": price - " + str(q[0].price))
                print(str(asset)+": vwap - " + str(q[0].vwap))
            except Exception as e:
                print(e)
                print(q)

    data_live = False

    def notify_data(self, data, status, *args, **kwargs):
        print('*' * 5, 'DATA NOTIF:', data._getstatusname(status), *args)

        if status == data.LIVE:
            self.data_live = True


def run(args=None):
    cerebro = bt.Cerebro(stdstats=False)
    store = bt.stores.IBStore(port=7496)
    # this lines does the magic of switching from broker simulation, to live trading on IB
    cerebro.broker = store.getbroker()

    '''
    symbols = ["SPY-STK-SMART-USD", "TLT-STK-SMART-USD"]

    data = store.getdata(dataname='SPY-STK-SMART-USD', timeframe=bt.TimeFrame.Ticks)    
    cerebro.resampledata(data, timeframe=bt.TimeFrame.Seconds, compression=10, name='SPY')
    # https://www.backtrader.com/docu/live/ib/ib.html - check whether this is necessary; maybe resampledata adds it already
    # cerebro.adddata(data)
    '''

    ib_name = '-STK-SMART-USD'
    assets = ['SPY']

    for symbol in assets:
        # TODO: Multiple Timeframe Datas can be used in backtrader with no special objects or tweaking: just add the smaller timeframes first.
        # https://www.backtrader.com/docu/data-multitimeframe/data-multitimeframe.html

        # Create the Data Feed for Cerebro
        ib_symbol = symbol + ib_name
        print(" Registering dataname: " + ib_symbol)
        data = store.getdata(dataname=ib_symbol, timeframe=bt.TimeFrame.Ticks)
        cerebro.resampledata(data, timeframe=bt.TimeFrame.Seconds, compression=10, name=symbol)

    cerebro.addstrategy(St)
    cerebro.run()


if __name__ == '__main__':
    run()
