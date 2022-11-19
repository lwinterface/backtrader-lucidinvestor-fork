#!/usr/bin/env python

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import backtrader as bt
from datetime import datetime
import pytz as tz


# used for testing with 50 tickers from sp500
# from pytickersymbols import PyTickerSymbols


class St(bt.Strategy):

    def __init__(self):
        # nb of next_live run before clean shutdown
        self.runtime = 10
        # buffer to load bid/ask in prenext
        self.bidask_buffer = False

        self.data_live = False
        self.not_yet_live = [d._id for d in self.datas]

    def prenext(self):
        '''
        hook to let developers access things before the following guarantee can be met:
            - guarantee: all buffers (indicators, data feeds) can deliver at least data point
            - alternative: see https://www.backtrader.com/blog/2019-05-20-momentum-strategy/momentum-strategy/
        :return:
        '''

        # if self.data.p.initial_tickPrice is True, it means we want to accelerate LIVE using initial TickPrice
        # if not - we do not accelerate, thus do not get into next()
        if not self.data.p.initial_tickPrice:
            return

        if self.bidask_buffer:
            print("\n PRENEXT sending to next")
            self.next()
        else:
            try:
                for asset in self.getdatanames():
                    ask = 0
                    bid = 0
                    close = 0
                    ask = self.datas[self.getdatanames().index(asset)].asklive['queue'].queue[-1].price
                    bid = self.datas[self.getdatanames().index(asset)].bidlive['queue'].queue[-1].price
                    close = self.datas[self.getdatanames().index(asset)].close[0]

                # buffer to load bid/ask in prenext
                self.bidask_buffer = True

            except Exception as e:
                print("\n BUFFERING BID-ASK. Issue with asset: " + str(asset))
                print(" the issue is with the 0: bid=" + str(bid) + " ask=" + str(ask) + " close=" + str(close))
                pass

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
                    print("error requesting bid/ask price (or bid/ask stream has been stopped)")

            self.runtime = self.runtime - 1

            if self.runtime < 1:
                self.env.runstop()


    def notify_data(self, data, status, *args, **kwargs):
        try:
            print("\n DATA NOTIF >> " + str(
                data._getstatusname(status)) + " instrument: " + data.tradecontract.m_localSymbol)
        except Exception as e:
            pass

        if status == data.LIVE:
            if data._id in self.not_yet_live:
                self.not_yet_live.remove(data._id)

            if len(self.data_live) < 1:
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

    # -> some stocks (like GSY invesco ultra short used for testing) would have a very low bid/ask price movement,
    # and thus would not trigger tickPrice or RTVolume quickly and would delay LIVE NOTIFICATION.
    ib_name = '-STK-SMART-USD'

    # used to get all sp500 tickers for testing
    # stock_data = PyTickerSymbols()
    # sp500_google = stock_data.get_sp_500_nyc_google_tickers()
    # sp500_tickers = [el.split(":",1)[1] for el in sp500_google]

    # assets = ["QQQ","TLT", "SPLV", "GSY", "SPY", "QLD", "UBT", "UGL", "GLD", "TIP", "DIA", "EUO", "SSO", "YCS", "DDM"]

    # 86
    # STE: this information is provided on an indicative basis only.
    # "HSIC" "ADI"
    assets = ["MMM", "AXP", "AAPL", "BA", "CAT", "CVX", "CSCO", "KO", "DD",
              "XOM", "GS", "GS", "HD", "IBM", "INTC", "JNJ", "JPM", "MCD", "NKE",
              "MRK", "MSFT", "PFE", "PG", "TRV", "UNH", "VZ", "V", "WMT", "WBA",
              "DIS", "ATVI", "ADBE", "AKAM", "GOOGL", "GOOG", "AMZN", "AAL", "AMGN", "TSLA",
              "ADSK", "CHTR", "CTSH", "CMCSA", "COST", "CSX", "XRAY", "DISH", "DLTR", "EBAY",
              "EA", "EXPE", "META", "FAST", "FISV", "GILD", "ILMN", "INCY", "INTU", "TMUS"]
    # "ISRG", "KHC", "LRCX", "MAR", "MCHP", "MU", "MDLZ", "MNST", "NTAP", "NFLX",
    # "NVDA", "NXPI", "ORLY", "PCAR", "PAYX", "PYPL", "QCOM", "REGN", "ROST", "STX",
    # "SWKS", "SBUX", "TMUS",  "TXN"]

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
