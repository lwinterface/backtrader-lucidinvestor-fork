#!/usr/bin/env python

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import time

import backtrader as bt
from datetime import datetime
import pytz as tz


# used for testing with 50 tickers from sp500
# from pytickersymbols import PyTickerSymbols


class St(bt.Strategy):

    def __init__(self):
        # nb of next_live run before clean shutdown
        self.runtime = 10
        self.datalivenotif = 0

        self.data_live = False
        self.not_yet_live = [d._id for d in self.datas]

    def prenext(self):
        pass

    def next(self):
        if self.data_live:
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("\n\n Current Time =", current_time)

            for asset in self.getdatanames():
                print("\n ASSET: " + str(asset) + "/ Close price: " + str(self.datas[self.getdatanames().index(asset)].close[0]))

            self.runtime = self.runtime - 1
            if self.runtime < 1:
                self.env.runstop()
        else:
            print("\n All data not LIVE, but I'm in next() !")


    def notify_data(self, data, status, *args, **kwargs):
        if status == data.LIVE:

            try:
                print("\n DATA NOTIF >> " + str(
                    data._getstatusname(status)) + " instrument: " + data.tradecontract.m_localSymbol)

                self.datalivenotif = self.datalivenotif + 1
                print(" This is data_notif = live number: " + str(self.datalivenotif) )

                if data._id in self.not_yet_live:
                    self.not_yet_live.remove(data._id)

                if len(self.not_yet_live) < 1:
                    self.data_live = True

            except Exception as e:
                print (" error with instrument: " + str(data.precontract.m_symbol))
                print (e)

def run(args=None):
    tz_default = tz.timezone('America/New_York')

    datakwargs = dict(
        backfill_start=False,
        backfill=False,
        timeframe=bt.TimeFrame.Seconds,
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

    # used to get all sp500 tickers for testing
    # stock_data = PyTickerSymbols()
    # sp500_google = stock_data.get_sp_500_nyc_google_tickers()
    # sp500_tickers = [el.split(":",1)[1] for el in sp500_google]

    ib_name = '-STK-SMART-USD'
    assets = ["MMM", "AXP", "AAPL", "BA", "CAT", "CVX", "CSCO", "KO", "DD",
              "XOM", "GS", "HD", "IBM", "INTC", "JNJ", "JPM", "MCD", "NKE",
              "MRK", "MSFT", "PFE", "PG", "TRV", "UNH", "VZ", "V", "WMT", "WBA",
              "DIS", "ATVI", "ADBE", "AKAM", "GOOGL", "GOOG", "AMZN", "AAL", "AMGN",
              "ADSK", "CHTR", "CTSH", "CMCSA", "COST", "CSX", "XRAY", "DISH", "DLTR", "EBAY",
              "EA", "EXPE", "META", "FAST", "FISV", "GILD", "INCY", "INTU", "TMUS"]
              #"ISRG", "KHC", "LRCX", "MAR", "MCHP", "MU", "MDLZ",
              #"MNST", "NTAP", "NFLX",]
              #"NVDA", "NXPI", "ORLY", "PCAR", "PAYX", "PYPL", "QCOM", "REGN", "ROST", "STX",
              #"SWKS", "SBUX", "TMUS", "TXN", "HSIC", "ADI", "TSLA", "ILMN",]

    #assets = ["SPY"]
    reg = 0
    for symbol in assets:
        # Create the Data Feed for Cerebro
        ib_symbol = symbol + ib_name
        reg = reg + 1
        print(" Registering dataname: " + ib_symbol + " - as number: " +str(reg))
        data = store.getdata(dataname=ib_symbol, **datakwargs)
        cerebro.resampledata(data, name=symbol, **rekwargs)

    cerebro.addstrategy(St)
    cerebro.run()


if __name__ == '__main__':
    run()
