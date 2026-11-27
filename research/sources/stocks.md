# R3 Stocks case studies: sources

36 public-equities trade cases (famous trades, earnings reactions, public contest results, retail case histories). All sources are public and free; no logins or paid data. Rows load into the shared trade_cases table via research/stocks_cases.py (fetch(con) -> int).

Verification policy: trades documented by SEC filings, sworn testimony, estate records or contemporaneous reporting by multiple major outlets are verified=1. Self-reported or organizer-published-only results (contest standings, Reddit P&L screenshots) are verified=0 with confidence <= 0.4 (survivorship bias applies).

## Cases and sources

### stocks-001: Herbalife (HLF) (loss, 2012-12)
- Source: https://www.cnbc.com/2018/02/28/ackman-exits-bet-against-herbalife.html
- Type: news | verified=1 | confidence=0.9
- P&L: covered Feb 2018 after ~5 years; stock well above 2012 entry; estimated loss near $1B

### stocks-002: IG/HY credit default swap indices (win, 2020-03)
- Source: https://www.cnbc.com/2020/03/25/bill-ackman-exits-market-hedges-uses-2-billion-he-made-to-buy-more-stocks-including-hilton.html
- Type: news | verified=1 | confidence=0.9
- P&L: about $2.6B gain in under a month; exited Mar 23-25, 2020

### stocks-003: Netflix (NFLX) (win, 2012-09)
- Source: https://www.cnbc.com/2015/06/24/carl-icahn-sells-last-of-netflix-shares.html
- Type: news | verified=1 | confidence=0.9
- P&L: roughly $1.6-2B profit; exited June 2015

### stocks-004: GameStop (GME) (win, 2019-08)
- Source: https://www.cnbc.com/2019/08/22/gamestop-surges-after-report-says-michael-burry-is-long-the-stock.html
- Type: news | verified=1 | confidence=0.6
- P&L: exited by Q4 2020, reportedly ~$100M gain, before the Jan 2021 squeeze peak

### stocks-005: GameStop (GME) (loss, 2021-01)
- Source: https://www.cnbc.com/2021/01/31/melvin-capital-lost-more-than-50percent-after-betting-against-gamestop-wsj.html
- Type: news | verified=1 | confidence=0.9
- P&L: about -53% of fund in Jan 2021 (~$4.5B) despite a $2.75B Citadel/Point72 infusion

### stocks-006: Valeant Pharmaceuticals (VRX) (loss, 2015-03)
- Source: https://www.reuters.com/article/us-valeant-ackman/ackmans-pershing-square-sells-valeant-stake-takes-3-billion-loss-idUSKBN16K2KT/
- Type: news | verified=1 | confidence=0.9
- P&L: sold entire stake Mar 2017; loss about $3-4B

### stocks-007: Green Mountain Coffee Roasters (GMCR) (win, 2011-10)
- Source: https://www.cnbc.com/2011/10/19/david-einhorns-case-against-green-mountain.html
- Type: news | verified=1 | confidence=0.9
- P&L: GMCR fell ~50% within weeks of the Oct 2011 presentation and kept sliding into 2012

### stocks-008: Enron (ENE) (win, 2000-11)
- Source: https://www.cnbc.com/2024/02/20/jim-chanos-on-his-legendary-enron-short-bet-2-decades-later.html
- Type: news | verified=1 | confidence=0.9
- P&L: shorted from the $70-90 area down toward the Dec 2001 bankruptcy

### stocks-009: CDS on subprime MBS / ABX indices (win, 2006-01)
- Source: https://www.wsj.com/articles/SB120036645057290423
- Type: news | verified=1 | confidence=0.9
- P&L: Paulson & Co made ~$15B in 2007; Paulson personally ~$4B

### stocks-010: Apple (AAPL) (win, 2016-01)
- Source: https://www.cnbc.com/2022/01/04/warren-buffett-makes-over-120-billion-on-apples-trot-to-3-trillion-among-his-best-bets-ever.html
- Type: news | verified=1 | confidence=0.9
- P&L: stake worth >$160B at early-2022 peak; >$120B unrealized profit

### stocks-011: Delta, American, United, Southwest (loss, 2016-01)
- Source: https://www.cnbc.com/2020/05/02/warren-buffett-says-berkshire-sold-its-entire-position-in-airlines-because-of-the-coronavirus.html
- Type: news | verified=1 | confidence=0.9
- P&L: sold entire position in four airlines in Apr 2020 at a loss Buffett called a mistake

### stocks-012: Meta Platforms (FB/META) (loss, 2022-02-02)
- Source: https://www.bbc.com/news/business-60255088
- Type: news | verified=1 | confidence=0.9
- P&L: -26.4% on Feb 3, 2022, erasing ~$251B; largest one-day value loss in market history at the time

### stocks-013: Netflix (NFLX) (loss, 2022-04-19)
- Source: https://www.cnbc.com/2022/04/20/netflix-plunges-trading-subscriber-loss.html
- Type: news | verified=1 | confidence=0.9
- P&L: about -35% on Apr 20, 2022, worst day since 2004

### stocks-014: momentum growth stocks (various) (win, 1997-01)
- Source: https://www.prnewswire.com/news-releases/stock-trader-wins-us-investing-championship-a-second-time--breaks-record-301466652.html
- Type: contest | verified=0 | confidence=0.4
- P&L: +155% (1997 USIC win) and +334.8% (2021 win, stock-division record)

### stocks-015: growth stocks (various) (win, 2020-01)
- Source: https://www.businesswire.com/news/home/20210125005140/en/U.S.-Investing-Championship-2020-Final-Standings
- Type: contest | verified=0 | confidence=0.4
- P&L: +941% in the 2020 USIC stock division

### stocks-016: GameStop (GME) (win, 2019-06)
- Source: https://www.congress.gov/117/meeting/house/111207/witnesses/HHRG-117-BA00-Wstate-GillK-20210218.pdf
- Type: testimony | verified=0 | confidence=0.4
- P&L: screenshots showed ~$48M at the Jan 2021 peak; realized P&L never audited

### stocks-017: blue-chip dividend stocks (Schering-Plough, Coca-Cola, others) (win, 1944-01)
- Source: https://www.nytimes.com/1995/12/02/nyregion/about-new-york-a-quiet-auditor-leaves-yeshiva-a-fortune.html
- Type: news | verified=1 | confidence=0.9
- P&L: ~$5,000 grew to ~$22M over 50 years; left to Yeshiva University

### stocks-018: Abbott Laboratories (ABT) (win, 1935-01)
- Source: https://www.lakeforest.edu/news/alumna-grace-groner-31-gives-7-million-to-lake-forest-college
- Type: news | verified=1 | confidence=0.9
- P&L: $180 became ~$7M by 2010, donated to Lake Forest College

### stocks-019: dividend-paying blue chips (J&J, P&G, railroads, banks) (win, 1959-01)
- Source: https://www.washingtonpost.com/business/get-there/the-remarkable-life-and-lessons-of-ronald-read/2015/04/24/7c12a26a-e944-11e4-9a6a-c1ab95a0600b_story.html
- Type: news | verified=1 | confidence=0.9
- P&L: ~$8M portfolio at death in 2014; $6M to a local library and hospital

### stocks-020: ViacomCBS, Discovery, GSX and others (loss, 2021-03)
- Source: https://www.cnbc.com/2021/04/27/ubs-nomura-push-global-banks-archegos-losses-over-10-billion.html
- Type: news | verified=1 | confidence=0.9
- P&L: family office wiped out; prime brokers lost >$10B (Credit Suisse ~$5.5B, Nomura ~$2.9B)

### stocks-021: Tesla (TSLA) (loss, 2017-01)
- Source: https://markets.businessinsider.com/news/stocks/tesla-stock-price-analysis-david-einhorn-greenlight-capital-short-2020-2021-1-1029992216
- Type: news | verified=1 | confidence=0.9
- P&L: Greenlight's biggest loser of 2020; fund returned ~5% in a year TSLA rose 743%

### stocks-022: Herbalife (HLF) (win, 2013-01)
- Source: https://www.reuters.com/business/carl-icahn-sells-over-half-his-herbalife-stake-600-million-2021-01-04/
- Type: news | verified=1 | confidence=0.6
- P&L: estimated profit around $1B; sold >half back to the company for $600M in Jan 2021, fully out by May 2021

### stocks-023: Alibaba (BABA) (loss, 2021-01)
- Source: https://www.reuters.com/business/daily-journal-long-overseen-by-charlie-munger-halves-stake-chinas-alibaba-2022-04-11/
- Type: news | verified=1 | confidence=0.9
- P&L: halved the stake in Q1 2022 after the stock fell 50%+ from purchases; large loss crystallized

### stocks-024: Luckin Coffee (LK) (win, 2019-11)
- Source: https://www.cnbc.com/2020/04/02/jim-chanos-says-he-covered-bet-against-chinas-luckin-coffee-amid-70percent-plunge-thursday.html
- Type: news | verified=1 | confidence=0.9
- P&L: covered Apr 2020 after Luckin fell ~70% in one day (~90% from highs)

### stocks-025: Bed Bath & Beyond (BBBY) (win, 2022-03)
- Source: https://www.cnbc.com/2022/08/18/activist-investor-ryan-cohen-completes-planned-sale-of-bed-bath-beyond-stake.html
- Type: news | verified=1 | confidence=0.9
- P&L: sold in Aug 2022 for about $58-68M profit; BBBY fell ~40% after his exit and later went bankrupt

### stocks-026: Legg Mason Value Trust portfolio (loss, 2006-01)
- Source: https://www.nytimes.com/2008/05/11/business/11bill.html
- Type: news | verified=1 | confidence=0.9
- P&L: Value Trust fell ~55% in 2008, erasing years of outperformance; the 15-year S&P-beating streak (1991-2005) ended badly

### stocks-027: Tiger Management funds (loss, 1999-01)
- Source: https://www.nytimes.com/2000/03/31/business/the-end-of-the-game-tiger-management-old-economy-advocate-is-closing.html
- Type: news | verified=1 | confidence=0.9
- P&L: closed Tiger in Mar 2000 after ~19% drop in early 2000 and heavy redemptions, weeks before the Nasdaq peaked

### stocks-028: Amazon (AMZN) (win, 2022-02-03)
- Source: https://www.reuters.com/business/amazon-surges-eyes-wall-street-record-gain-value-2022-02-04/
- Type: news | verified=1 | confidence=0.9
- P&L: about +14% on Feb 4, 2022, the largest single-day market-value gain in US market history at the time

### stocks-029: BYD (1211.HK) (win, 2008-09)
- Source: https://fortune.com/2021/03/02/warren-buffett-investments-berkshire-hathaway-byd/
- Type: news | verified=1 | confidence=0.9
- P&L: stake worth ~$6-9B+ by 2021-2024; Berkshire trimmed from 2022 with billions in profit

### stocks-030: PetroChina (0857.HK) (win, 2002-01)
- Source: https://www.cnbc.com/2007/10/19/warren-buffett-sold-entire-petrochina-stake-due-to-price-rise-darfur-not-a-factor.html
- Type: news | verified=1 | confidence=0.9
- P&L: sold in 2007 for about $4B; profit ~$3.5B

### stocks-031: CDS on subprime mortgage bonds (win, 2005-01)
- Source: https://archive.nytimes.com/dealbook.nytimes.com/2010/03/01/michael-burry-the-man-who-shorted-subprime/index.html
- Type: news | verified=1 | confidence=0.9
- P&L: Scion returned roughly +489% net from inception to mid-2008, driven by the subprime short; investors were restricted from redeeming during the wait

### stocks-032: Tesla (TSLA) (loss, 2020-01)
- Source: https://www.bloomberg.com/news/articles/2020-12-31/tesla-shorts-sellers-lost-38-billion-in-2020-as-stock-surged
- Type: news | verified=1 | confidence=0.9
- P&L: short sellers lost about $38B mark-to-market in 2020 as TSLA rose ~743%

### stocks-033: Snap (SNAP) (loss, 2022-05-23)
- Source: https://www.cnbc.com/2022/05/24/snaps-down-32percent-and-its-dragging-other-stocks-down-with-it.html
- Type: news | verified=1 | confidence=0.9
- P&L: -43% on May 24, 2022, Snap's worst day ever, below its IPO price; dragged ad-tech peers down with it

### stocks-034: Kraft Heinz (KHC) (loss, 2015-07)
- Source: https://www.cnbc.com/2019/02/25/buffett-says-berkshire-hathaway-overpaid-for-kraft-following-last-weeks-stock-plunge.html
- Type: news | verified=1 | confidence=0.9
- P&L: $15B Kraft Heinz writedown Feb 2019; Berkshire lost ~$4B in one day on the stock's ~27% plunge; Buffett admitted overpaying

### stocks-035: Zoom Video (ZM) (loss, 2020-10)
- Source: https://www.reuters.com/business/zoom-shares-down-90-peak-pandemic-boom-fades-2022-11-22/
- Type: news | verified=1 | confidence=0.9
- P&L: down ~90% from the Oct 2020 peak by Nov 2022

### stocks-036: Peloton (PTON) (loss, 2021-01)
- Source: https://www.nasdaq.com/articles/peloton-stock-sinks-over-92-in-one-year-recovery-a-far-cry
- Type: news | verified=1 | confidence=0.9
- P&L: down >92% within about a year of the Jan 2021 peak; fell below its IPO price in Jan 2022

## Notes on source quality

- stocks-001, 003, 005, 006, 011, 021-024, 025-027, 029, 030, 034: positions and P&L confirmed through SEC filings (13D/13F), company releases or fund letters, plus major-outlet reporting.
- stocks-012, 013, 028, 033, 035, 036: market-wide earnings/reaction events; figures from Reuters/CNBC/BBC same-day reporting.
- stocks-014, 015: US Investing Championship standings are organizer-published; stated to be verified against brokerage statements, but not independently auditable by us: verified=0.
- stocks-016: Keith Gill's realized P&L rests on his own posts and testimony; position direction and thesis are documented, exact profit is not: verified=0.
- stocks-017-019: estate-documented long-term compounding cases (NYT, Lake Forest College, Washington Post).