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

        print(" cash = " + str(self.broker.getcash()))
        print (" portfolio allocation = " +str(self.get_total_portfolio_allocation() ))

        if self.data_live == True and False:

            for asset in self.getdatanames():
            #asset = self.getdatanames()[0]

                print("\n ASSET: " +str(asset))

                q = self.datas[self.getdatanames().index(asset)].qlive.queue
                print(str(asset) + "/ Close price: " + str(self.datas[self.getdatanames().index(asset)].close[0]))
                print(str(asset)+ "/ len qlive: " +str(len(q)))
                try:
                    print("\n"+ str(asset) +": price - " + str(q[0].price))
                    print(str(asset)+": vwap - " + str(q[0].vwap))
                except Exception as e:
                    print(e)
                    print(q)

                try:
                    ask = self.datas[self.getdatanames().index(asset)].bidasklive.queue[-1].ask
                    bid = self.datas[self.getdatanames().index(asset)].bidasklive.queue[-1].bid
                    print(" last ask price is: " + str(float(ask)) + " last bid price is: " + str(float(bid)) )
                    print(" len ask: " + str(len(self.datas[self.getdatanames().index(asset)].bidasklive.queue)))
                except Exception as e:
                    print(e)
                    print("error requesting bid/ask price")

    data_live = False

    def notify_data(self, data, status, *args, **kwargs):
        print('*' * 5, 'DATA NOTIF:', data._getstatusname(status), *args)

        if status == data.LIVE:
            self.data_live = True

    def get_total_portfolio_allocation(self, cash_usdsecurity=100):
        # MINIMUM COSTS
        # monthly minimum for IB = 10
        # three subscriptions AMEX Level I, NASDAQ Level I, NYSE Level I = total $4.5 ( $1.5each)
        min_costs = 1.10 * (10 + 3 * (1.5))

        # make sure this is a single account login
        if len(self.broker.ib.managed_accounts) > 1:
            msg = "\n\n[OrderManager.__init__]"
            msg = msg + "MORE THAN ONE MANAGED ACCOUNT AVAILABLE - DO NOT USE MULTI-ACCT LOGIN"
            self.add_log('error', msg)
            exit()

        accountid = self.broker.ib.managed_accounts[0]
        cash_usd = self.broker.ib.acc_upds[accountid].CashBalance.USD
        cash_total = self.broker.ib.acc_upds[accountid].CashBalance.Base
        cash_notconverted = cash_total - cash_usd

        cash_totalreserve = cash_usdsecurity + cash_notconverted
        if cash_totalreserve < min_costs + cash_notconverted:
            cash_totalreserve = min_costs + cash_notconverted
            msg = "\n\n[OrderManager.get_allocation]"
            msg = msg + "cash_usdsecurity entered was too small - using min_costs default = IB(10$)+LvlI Amex/NASDAQ/NYSE (3*1.5)"
            self.add_log('warning', msg)

        # broker.getvalue() = cash + open position
        portfolio_allocation = 1 - (cash_totalreserve / float(self.broker.getvalue()))
        return portfolio_allocation


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
    assets = ['QQQ', 'SPY']

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
