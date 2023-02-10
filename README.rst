backtrader
**********

credits
#######

original author: Daniel Rodriguez (danjrod@gmail.com)
original unmaintained github: https://github.com/mementum/backtrader
alternative unmaintained github: https://github.com/backtrader2/backtrader

Tickets
#######

The ticket system is available at `LucidInvestor's public gitlab instance <https://gitlab.com/algorithmic-trading-library/backtrader/-/issues>`_.

Here a snippet of a Simple Moving Average CrossOver. It can be done in several
different ways. Use the docs (and examples) Luke!
::

  from datetime import datetime
  import backtrader as bt

  class SmaCross(bt.SignalStrategy):
      def __init__(self):
          sma1, sma2 = bt.ind.SMA(period=10), bt.ind.SMA(period=30)
          crossover = bt.ind.CrossOver(sma1, sma2)
          self.signal_add(bt.SIGNAL_LONG, crossover)

  cerebro = bt.Cerebro()
  cerebro.addstrategy(SmaCross)

  data0 = bt.feeds.YahooFinanceData(dataname='MSFT', fromdate=datetime(2011, 1, 1),
                                    todate=datetime(2012, 12, 31))
  cerebro.adddata(data0)

  cerebro.run()
  cerebro.plot()

Including a full featured chart. Give it a try! This is included in the samples
as ``sigsmacross/sigsmacross2.py``. Along it is ``sigsmacross.py`` which can be
parametrized from the command line.

Installation
############

``backtrader`` is self-contained with no external dependencies (except if you
want to plot)

From *pypi*:

  - ``pip install backtrader-lucidinvestor``

  - ``pip install backtrader[plotting]``

    If ``matplotlib`` is not installed and you wish to do some plotting

.. note:: The minimum matplotlib version is ``1.4.1``

An example for *IB* Data Feeds/Trading:

  - ``IbPy`` ``pip install IbPy-lucidinvestor``

For other functionalities like: ``Visual Chart``, ``Oanda``, ``TA-Lib``, check
the dependencies in the documentation.

From source:

  - Place the *backtrader* directory found in the sources inside your project

Python 2/3 Support
##################

  - Python >= ``3.2``

  - It also works with ``pypy`` and ``pypy3`` (no plotting - ``matplotlib`` is
    not supported under *pypy*)

Features
********

Live Trading and backtesting platform written in Python.

  - Live Data Feed and Trading with

    - Interactive Brokers (needs ``IbPy`` and benefits greatly from an
      installed ``pytz``)
    - *Visual Chart* (needs a fork of ``comtypes`` until a pull request is
      integrated in the release and benefits from ``pytz``)
    - *Oanda* (needs ``oandapy``) (REST API Only - v20 did not support
      streaming when implemented)

  - Data feeds from csv/files, online sources or from *pandas* and *blaze*
  - Filters for datas, like breaking a daily bar into chunks to simulate
    intraday or working with Renko bricks
  - Multiple data feeds and multiple strategies supported
  - Multiple timeframes at once
  - Integrated Resampling and Replaying
  - Step by Step backtesting or at once (except in the evaluation of the Strategy)
  - Integrated battery of indicators
  - *TA-Lib* indicator support (needs python *ta-lib* / check the docs)
  - Easy development of custom indicators
  - Analyzers (for example: TimeReturn, Sharpe Ratio, SQN) and ``pyfolio``
    integration (**deprecated**)
  - Flexible definition of commission schemes
  - Integrated broker simulation with *Market*, *Close*, *Limit*, *Stop*,
    *StopLimit*, *StopTrail*, *StopTrailLimit*and *OCO* orders, bracket order,
    slippage, volume filling strategies and continuous cash adjustmet for
    future-like instruments
  - Sizers for automated staking
  - Cheat-on-Close and Cheat-on-Open modes
  - Schedulers
  - Trading Calendars
  - Plotting (requires matplotlib)

Documentation
*************

The blog:

  - `Blog <http://www.backtrader.com/blog>`_

Read the full documentation at:

  - `Documentation <http://www.backtrader.com/docu>`_

List of built-in Indicators (122)

  - `Indicators Reference <http://www.backtrader.com/docu/indautoref.html>`_

Version numbering
*****************

X.Y.Z.I

  - X: Major version number. Should stay stable unless something big is changed
    like an overhaul to use ``numpy``
  - Y: Minor version number. To be changed upon adding a complete new feature or
    (god forbids) an incompatible API change.
  - Z: Revision version number. To be changed for documentation updates, small
    changes, small bug fixes
  - I: Number of Indicators already built into the platform

major Branches
##############

* **master**  - Merge from Develop. QA for full integration happens here.
  Contains the last tested/verified global code integration.
* **release** - Checkout from Master. Branch based on release & tags. Bug fix in checkout branches,
  and merge with others.
* **develop** - Checkout from Master / Pull.Req from Develop. Develop new features, docs ...
* **bug** - checkout from master and pull.req. OR checkout from release branch and pull.req/Master
* **features** -  checkout Develop.

Branch naming conventions
#########################

shall follow that of [GroupName/Info](http://stackoverflow.com/questions/273695/git-branch-naming-best-practices):

1. Use **grouping names** at the beginning of your branch names.
2. Define and use short **lead tokens** to differentiate branches in a way that is meaningful to your workflow.
3. Use slashes to separate parts of your branch names.
4. Do not use bare numbers as leading parts.
5. Avoid long descriptive names for long-lived branches.

Grouping Names
##############

Short and well-defined group names (used to tell you to which part of your workflow each branch belongs):
`code-block/ text`

- **rc** release candidate
- **new** major new feature, module
- **feat** addition of incremental feature/enhancement
- **bug** Bug fix
- **junk** Throwaway branch created to experiment
- **test**
- **doc** documentation (readme, code comment)

Commit messages
###############

Standard prefixes to start a commit message: `code-block:: text`

-   **BLD** change related to build
-   **BUG** bug fix
-   **DEP** deprecate something, or remove a deprecated object
-   **DEV** development tool or utility
-   **DOC** documentation
-   **ENH** enhancement
-   **MAINT** maintenance commit (refactoring, typos, etc)
-   **REV** revert an earlier commit
-   **STY** style fix (whitespace, PEP8, flake8, etc)
-   **TST** addition or modification of tests
-   **REL** related to releasing
-   **PERF** performance enhancements


Some commit style guidelines:

Commit lines should be no longer than `72 characters`__. The first line of the commit should include one of the above prefixes. There should be an empty line between the commit subject and the body of the commit. In general, the message should be in the imperative tense. Best practice is to include not only what the change is, but why the change was made.

__ https://git-scm.com/book/en/v2/Distributed-Git-Contributing-to-a-Project


Repo Structure
##############

git remote add bt2-original https://github.com/backtrader2/backtrader.git
git fetch bt2-original master
git branch –set-upstream-to=bt2-original/master
git pull
git push origin -u bt2/original/master

git remote -v


    bt-original     https://github.com/mementum/backtrader.git (fetch)
    bt-original     https://github.com/mementum/backtrader.git (push)
    bt2-original    https://github.com/backtrader2/backtrader.git (fetch)
    bt2-original    https://github.com/backtrader2/backtrader.git (push)
    mementum        https://github.com/mementum/backtrader.git (fetch)
    mementum        https://github.com/mementum/backtrader.git (push)
    origin  git@gitlab.com:algorithmic-trading-library/backtrader.git (fetch)
    origin  git@gitlab.com:algorithmic-trading-library/backtrader.git (push)


git branch -vv

      bt/original/develop  fca15d9 [origin/bt/original/develop] Release 1.9.75.123
      bt/original/master   0fa63ef [origin/bt/original/master] Merge pull request #418 from Larry-u/patch-1
      bt2/original/develop ef00a78 [origin/bt2/original/develop] Merge branch 'master' of https://github.com/backtrader2/backtrader into bt2/original/master
      bt2/original/master  ef00a78 [origin/bt2/original/master] Merge branch 'master' of https://github.com/backtrader2/backtrader into bt2/original/master
      develop              9f843b0 MAINT: making things cleaner for testing bid/ask.
      development          9f843b0 [origin/development: gone] MAINT: making things cleaner for testing bid/ask.
      feat/ib/bidask       dcb4c1a Release 1.9.74.123
      feat/ib/rt-bidask    7b366cd [origin/feat/ib/rt-bidask] FEAT: bid/ask stream. on and off. tested live.
      master               9f843b0 [origin/master] MAINT: making things cleaner for testing bid/ask.

Fetching all remote branches
############################

    for abranch in $(git branch -a | grep -v HEAD | grep remotes | sed "s/remotes\/origin\///g"); do git checkout $abranch ; done


