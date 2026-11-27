# R2 Forex case studies - source register

Collected 2026-11-27 (Africa/Cairo). All sources are public and free: no logins, no paid data, no contact with anyone.

## Method and caveats

- One row per case in `research/cases/forex.json`; this file is the human-readable provenance for each `source_url`.
- `verified=1` means the underlying facts come from an authoritative or independently reported public source (central bank, IMF/BIS/Fed, SEC filing, regulator, or established news outlet). It does not certify every number in the secondary coverage.
- `verified=0` marks self-reported forum material. Per workstream rules these are capped at confidence 0.4 because of survivorship bias: people post wins and confessions selectively, so forum cases are anecdotes about failure modes, not base rates.
- Losses are documented with the same why/how/where detail as wins; roughly two thirds of this set are loss or mixed outcomes by design.
- Reported figures (position sizes, P&L) that rest on a single outlet or an unnamed source are hedged inside the case text itself (e.g. Everest Capital, Soros position size).

## Cases

### forex-001 - EUR/CHF (loss, verified=1, confidence=0.95)
- source: https://www.snb.ch/public/asset/en/www-snb-ch/publications/communication/press-releases/2015/pre_20150115/publications0_en/pre_20150115.en.pdf
- source_type: central_bank; tags: central-bank,peg-break,gap-risk,loss
- what: On 15 Jan 2015 the SNB discontinued the CHF 1.20 minimum exchange rate vs the euro without warning and cut its rate to -0.75%, saying the overvaluation had decreased while the euro was weakening globally.
- lesson: Central bank floors are political decisions that can vanish overnight; gap risk overwhelms stop placement on one-way peg trades.

### forex-002 - EUR/CHF (loss, verified=1, confidence=0.9)
- source: https://www.sec.gov/Archives/edgar/data/1499912/000114420415002475/v398872_ex99-1.htm
- source_type: sec_filing; tags: broker-risk,negative-balance,gap-risk,loss
- what: The SNB floor removal caused unprecedented EUR/CHF volatility; FXCM's own SEC-filed release says clients experienced significant losses generating negative equity balances of about $225M.
- lesson: Broker counterparty solvency is part of trade risk; negative-balance protection did not exist yet for these accounts.

### forex-003 - CHF crosses (short CHF bias) (loss, verified=1, confidence=0.85)
- source: https://www.reuters.com/article/business/large-everest-capital-hedge-fund-closing-after-swiss-franc-losses-bloomberg-idUSKBN0KQ0N0/
- source_type: news; tags: hedge-fund,blowup,peg-break,loss
- what: Everest's largest fund had been betting the Swiss franc would decline when the SNB scrapped the cap; Bloomberg reporting (via Reuters) cited a person familiar with the firm.
- lesson: Even professional macro funds die on peg breaks when leverage meets a discontinuous policy repricing.

### forex-004 - EUR/CHF (win, verified=1, confidence=0.9)
- source: https://www.snb.ch/en/publications/communication/press-releases/2011/pre_20110906
- source_type: central_bank; tags: central-bank,intervention,peg,win
- what: On 6 Sep 2011 the SNB set a minimum exchange rate of CHF 1.20 per euro, calling the franc's value a threat to the Swiss economy, and committed to enforce it with unlimited FX purchases.
- lesson: A central bank with unlimited balance sheet can dominate the exchange rate; align with credible commitments, fade them only when the politics crack (see forex-001).

### forex-005 - GBP/DEM, GBP/USD (win, verified=1, confidence=0.9)
- source: https://www.theguardian.com/business/2012/sep/13/black-wednesday-20-years-pound-erm
- source_type: news; tags: peg-break,speculative-attack,win
- what: Sterling joined the ERM in 1990 and struggled to hold its band; on 16 Sep 1992 speculators attacked, the Bank of England's defense failed, and the UK quit the mechanism the same day.
- lesson: A peg inconsistent with domestic economics is a one-way bet: limited downside for attackers, unlimited cost for defenders.

### forex-006 - GBP/DEM (win, verified=1, confidence=0.8)
- source: https://www.investopedia.com/ask/answers/08/george-soros-bank-of-england.asp
- source_type: news; tags: macro,speculative-attack,leverage,win
- what: Soros judged Britain's ERM position unsustainable and that sterling would have to devalue or leave; he built the most prominent short among many speculators.
- lesson: Reflexivity: a large enough actor's positioning helps cause the outcome it predicts; position sizing matched conviction.

### forex-007 - GBP/USD (loss, verified=1, confidence=0.9)
- source: https://www.reuters.com/article/global-markets-idUSL4N19F52Z/
- source_type: news; tags: event-risk,political,gap-risk,loss
- what: The UK voted to leave the EU on 23 Jun 2016 against market pricing; results through the night turned Remain optimism into a record sterling plunge, with the euro sliding 3.1% too.
- lesson: Binary event outcomes cannot be hedged by conviction in polls; event risk demands flat books or optionality, not directional leverage.

### forex-008 - GBP/USD (mixed, verified=1, confidence=0.85)
- source: https://www.bloomberg.com/news/articles/2016-10-06/pound-plunges-6-1-percent-in-biggest-drop-since-brexit-result
- source_type: news; tags: flash-crash,liquidity,algos
- what: On 7 Oct 2016 the pound plunged 6.1% in minutes during Asian hours, its biggest drop since the Brexit vote, with traders blaming computer-initiated sell orders (a fat finger or algos).
- lesson: Session liquidity is a risk factor: the same position is far riskier at illiquid hours; flash crashes punish tight stops and reward liquidity provision.

### forex-009 - USD/JPY (win, verified=1, confidence=0.95)
- source: https://www.reuters.com/markets/currencies/japan-confirms-fx-interventions-twice-oct-support-yen-2023-02-07/
- source_type: news; tags: central-bank,intervention,yen,win
- what: USDJPY hit a 32-year low for the yen at 151.94 on 21 Oct 2022 as the BoJ held ultra-low rates while the Fed hiked; Japan's MoF confirmed record yen-buying intervention on 21 and 24 Oct.
- lesson: Intervention works best when deployed against stretched one-way positioning at obvious levels; size disclosure is part of the weapon.

### forex-010 - USD/JPY (mixed, verified=1, confidence=0.9)
- source: https://www.mof.go.jp/english/policy/international_policy/reference/feio/quarter/2024_2Qe.html
- source_type: central_bank; tags: central-bank,intervention,yen
- what: Japan's Ministry of Finance disclosed 9.79 trillion yen of FX intervention operations for April-June 2024, defending the yen at multi-decade extremes of dollar strength.
- lesson: Intervention can buy time and punish shorts, but cannot hold a level against an unchanged interest-rate differential.

### forex-011 - USD/JPY (loss, verified=1, confidence=0.9)
- source: https://www.reuters.com/markets/currencies/yen-rises-7-month-highs-us-slowdown-fears-carry-over-2024-08-05/
- source_type: news; tags: carry-trade,unwind,risk-off,loss
- what: Weak US jobs data, disappointing big-tech earnings and China concerns sparked a global selloff and rate-cut bets; the yen surged as crowded carry positions unwound into 5 Aug 2024.
- lesson: Carry trades earn small steady differentials and lose them back in days when volatility regime-shifts; funding currency choice is risk selection.

### forex-012 - USD/JPY (loss, verified=1, confidence=0.9)
- source: https://www.federalreserve.gov/pubs/ifdp/2007/899/ifdp899.htm
- source_type: central_bank; tags: carry-trade,unwind,ltcm,loss
- what: Immediately after the LTCM crisis, banks cut leverage to hedge fund clients; the Fed's IFDP 899 identifies October 1998 as the most dramatic episode of yen carry-trade unwinding.
- lesson: Carry unwinds are driven by lender margin calls, not just rate differentials; funding-side leverage is the hidden variable.

### forex-013 - USD/TRY (loss, verified=1, confidence=0.85)
- source: https://www.bbc.com/news/world-europe-45142256
- source_type: news; tags: em,carry,credibility,loss
- what: The BBC's explainer records the lira nosediving through 2018 as investors lost confidence in Turkey's policy mix: political pressure for low rates, large dollar-denominated corporate debt, and a diplomatic rift with the US.
- lesson: High nominal yield is compensation for policy-credibility risk; when the central bank is not independent, carry is not a free lunch.

### forex-014 - USD/TRY (loss, verified=1, confidence=0.8)
- source: https://www.kbc.com/en/economics/publications/turkey-testing-the-limits-of-unorthodoxy.html
- source_type: research; tags: em,unorthodox-policy,credibility,loss
- what: KBC's economic analysis describes Turkey 'testing the limits of unorthodoxy': repeated policy rate cuts under political pressure despite elevated inflation, eroding the lira through 2021.
- lesson: A currency's floor is set by policy credibility, not by how cheap it looks; negative real rates invite structural depreciation.

### forex-015 - USD/RUB (loss, verified=1, confidence=0.9)
- source: https://www.reuters.com/article/idUSL6N0TZ48Q20141215/
- source_type: news; tags: em,commodity-currency,sanctions,emergency-hike
- what: Falling oil prices and sanctions over the Ukraine crisis pushed Russia toward recession; on 16 Dec 2014 the central bank raised its key rate to 17% in an emergency move to halt the ruble's collapse.
- lesson: Commodity terms-of-trade shocks plus sanctions can overpower even extreme rate defenses; position sizing must assume policy arrives late.

### forex-016 - USD/RUB (mixed, verified=1, confidence=0.9)
- source: https://www.reuters.com/business/finance/russias-rouble-rebound-not-quite-what-it-seems-2022-04-08/
- source_type: news; tags: capital-controls,sanctions,price-discovery
- what: After the invasion of Ukraine the ruble crashed to a record 121.52 per dollar on 10 Mar 2022, then staged an apparently extraordinary recovery that Reuters showed was not what it seemed: capital controls made the exchange rate artificial.
- lesson: Under capital controls the quoted FX rate is a policy artifact, not a tradable price; mark positions to the rate you can actually transact at.

### forex-017 - USD/THB (win, verified=1, confidence=0.85)
- source: https://www.chicagofed.org/publications/chicago-fed-letter/2001/january-161
- source_type: central_bank; tags: peg-break,speculative-attack,contagion,asia-1997
- what: On 2 Jul 1997 Thailand abandoned its dollar peg after sustained speculative attack, triggering the Asian financial crisis; the Chicago Fed retrospective asks whether it was foreseen given the warning signs.
- lesson: Peg attacks are contagious: the same vulnerability map (fixed rate, weak reserves, external deficits) gets repriced everywhere at once.

### forex-018 - USD/CNY (loss, verified=1, confidence=0.9)
- source: https://www.reuters.com/article/business/yuan-slumps-for-second-day-to-four-year-low-roils-global-markets-idUSKCN0QH0CW/
- source_type: news; tags: managed-float,pboc,signal-risk
- what: On 11 Aug 2015 the PBoC revised how it calculates the daily guidance rate to better reflect market forces; the yuan fell sharply for two days to a four-year low, startling markets that read it as competitive devaluation.
- lesson: In managed regimes the signal value of a fix change matters more than its size; watch the fixing mechanism, not just the level.

### forex-019 - GBP/USD (loss, verified=1, confidence=0.9)
- source: https://www.reuters.com/markets/europe/uk-bonds-pound-centre-storm-tax-shock-hammers-confidence-2022-09-23/
- source_type: news; tags: fiscal-risk,gilts,event-risk,loss
- what: Chancellor Kwarteng's mini-budget promised 45 billion pounds a year of permanent tax cuts plus energy support, requiring 72 billion pounds of extra borrowing in six months; investors choked on the prospect and hammered both gilts and sterling.
- lesson: In a twin-deficit country, fiscal credibility is the exchange rate; currency and bond risk are the same trade at stress points.

### forex-020 - EUR/ISK, USD/ISK (loss, verified=1, confidence=0.85)
- source: https://www.imf.org/en/news/articles/2015/09/28/04/53/soint111908a
- source_type: international_org; tags: banking-crisis,twin-crisis,loss
- what: The IMF's post-crisis interview explains Iceland allowed a banking system to grow from about 100% to close to 1000% of GDP after 2003 privatization, vastly outstripping the authorities' ability to act as lender of last resort.
- lesson: A currency is only as strong as the state's capacity to backstop its banking system; bank-sector size relative to GDP is an FX risk metric.

### forex-021 - USD/JPY, USD/DEM (loss, verified=1, confidence=0.9)
- source: https://www.g7.utoronto.ca/finance/fm850922.htm
- source_type: primary_document; tags: coordinated-intervention,plaza,regime-change
- what: On 22 Sep 1985 the G5 ministers and governors announced agreement that further orderly appreciation of the main non-dollar currencies against the dollar was desirable, committing to coordinated intervention.
- lesson: When major central banks coordinate against a currency, the policy signal itself is the trade; fighting coordinated intervention is fighting five balance sheets.

### forex-022 - USD/MXN (loss, verified=1, confidence=0.8)
- source: https://en.wikipedia.org/wiki/Mexican_peso_crisis
- source_type: encyclopedia; tags: peg-break,em,debt-mismatch,loss
- what: In December 1994 Mexico's crawling-peg defense failed amid political shocks and dollar-linked tesobono debt; the peso was devalued then floated, roughly halving in value before stabilizing.
- lesson: Currency mismatch on the sovereign's own balance sheet converts a defense into an accelerant; check what the defender owes before trusting the peg.

### forex-023 - USD/BRL (loss, verified=1, confidence=0.9)
- source: https://www.dallasfed.org/~/media/documents/research/swe/1999/swe9902c.pdf
- source_type: central_bank; tags: peg-break,em,contagion,reserves
- what: The Dallas Fed's retrospective explains Brazil's Real Plan peg/crawling band could not offset cumulative inflation differentials; contagion from Asia 1997 and Russia 1998 drove outflows that rate hikes and half the reserves could not stop.
- lesson: Crawling pegs die by cumulative overvaluation, not by a single shock; reserve trajectory is the tell.

### forex-024 - USD/ARS (loss, verified=1, confidence=0.85)
- source: https://www.imf.org/en/news/articles/2018/06/20/pr18245-argentina-imf-executive-board-approves-us50-billion-stand-by-arrangement
- source_type: international_org; tags: em,carry,imf,loss
- what: In 2018 a run on the peso driven by inflation, fiscal deficits and drought-hit exports forced Argentina to the IMF; on 20 Jun 2018 the Board approved a US$50B three-year stand-by arrangement.
- lesson: When the carry trade on an EM currency ends at the IMF's door, the yield was the risk premium all along.

### forex-025 - USD/ARS (official) (loss, verified=1, confidence=0.9)
- source: https://www.bloomberg.com/news/articles/2023-12-12/argentina-s-milei-devalues-peso-by-54-in-first-batch-of-shock-measures
- source_type: news; tags: devaluation,administered-rate,em,loss
- what: On 12 Dec 2023 the Milei government devalued the peso by 54% as the first batch of shock measures, setting the official rate at 800 per dollar with a 2% monthly crawl, alongside subsidy cuts.
- lesson: In administered regimes the overnight devaluation risk is the position; local-currency exposure carries full adjustment risk regardless of hedges priced off the official rate.

### forex-026 - EUR/USD (loss, verified=1, confidence=0.9)
- source: https://www.reuters.com/markets/europe/euro-is-parity-its-fate-is-now-with-energy-markets-2022-07-13/
- source_type: news; tags: terms-of-trade,energy,parity,loss
- what: On 13 Jul 2022 the euro broke parity with the dollar for the first time in twenty years as the energy price shock from the Ukraine conflict threatened a prolonged European economic crisis, while the Fed out-hiked the ECB.
- lesson: Terms-of-trade shocks can dominate rate differentials for commodity importers; the currency is where the energy bill shows up first.

### forex-027 - USD/LKR (loss, verified=1, confidence=0.85)
- source: https://www.elibrary.imf.org/view/journals/002/2023/116/article-A001-en.xml
- source_type: international_org; tags: em,default,reserves,imf,loss
- what: The IMF's 2023 staff report records that preexisting vulnerabilities, significant policy missteps (including late-2019 tax cuts costing over 2% of GDP in revenue) and major shocks produced Sri Lanka's full-blown 2022 crisis.
- lesson: Reserve adequacy is the binding constraint on an EM currency; when reserves approach zero, the exchange rate is a countdown timer.

### forex-028 - USD/ZAR (loss, verified=1, confidence=0.85)
- source: https://www.bloomberg.com/news/articles/2015-12-09/south-africa-removes-finance-minister-triggering-slump-in-rand
- source_type: news; tags: political-risk,em,event-risk,loss
- what: On 9 Dec 2015 President Zuma fired finance minister Nhlanhla Nene and replaced him with a little-known lawmaker, triggering the rand's biggest fall in over four years as fiscal-guardrail credibility was repriced instantly.
- lesson: In credibility-scarce markets, institutional personnel are a macro variable; political event risk can gap a currency without any economic release.

### forex-029 - AUD/JPY (loss, verified=1, confidence=0.9)
- source: https://www.rba.gov.au/publications/bulletin/2009/may/1.html
- source_type: central_bank; tags: carry-trade,unwind,feedback-loop,loss
- what: The RBA's May 2009 Bulletin documents how carry trades in the Australian dollar unwound as the sharp AUD/JPY depreciation made positions unprofitable: the exchange-rate move swamped the small stable interest differential.
- lesson: Carry is short volatility: the exchange-rate leg, not the rate differential, decides the P&L in a crisis, and the unwind feeds itself.

### forex-030 - USD/JPY, AUD/JPY (mixed, verified=1, confidence=0.9)
- source: https://www.rba.gov.au/publications/smp/2019/feb/pdf/box-b-the-recent-japanese-yen-flash-event.pdf
- source_type: central_bank; tags: flash-crash,liquidity,yen
- what: The RBA's Box B documents the 3 Jan 2019 flash event: the yen appreciated very sharply over a few minutes around the Asian open and cascaded across markets, with AUD depreciating sharply in low liquidity.
- lesson: Flash events cluster in predictable low-liquidity windows; avoid holding leveraged exposure through holiday Asian opens.

### forex-031 - USD index / USD funding (loss, verified=1, confidence=0.85)
- source: https://www.bis.org/publications/bulletin-14-us-dollar-funding-markets-during-covid-19-crisis-money-market-fund-turmoil.pdf
- source_type: research; tags: dollar-funding,crisis,basis,loss
- what: The BIS Bulletin documents how Covid-19 stress in March 2020 produced turmoil in US dollar funding markets and money market funds: everyone demanded dollars at once, and the dollar spiked against nearly everything.
- lesson: In a global crisis the dollar is a funding liability, not a currency view; the FX swap basis reveals funding stress before spot does.

### forex-032 - EUR/USD (loss, verified=1, confidence=0.8)
- source: http://www.crandallhenning.com/uploads/2/9/3/5/29350993/organizing_foreign_exchange_intervention_in_the_euro_area.pdf
- source_type: research; tags: credibility,new-currency,ecb,loss
- what: Randall Henning's study of euro-area intervention records that the euro opened at $1.17 on 4 Jan 1999, near economists' equilibrium estimates, yet slid through 1999-2000 amid strong-US growth expectations and cacophonous ECB communication.
- lesson: Institutional credibility and message discipline are priced into a currency; 'fair value' is not a floor when governance is unproven.

### forex-033 - retail FX CFDs (loss, verified=1, confidence=0.85)
- source: https://www.esma.europa.eu/press-news/esma-news/esma-agrees-prohibit-binary-options-and-restrict-cfds-protect-retail-investors
- source_type: regulator_stats; tags: retail-stats,regulation,leverage,loss
- what: On 27 Mar 2018 ESMA agreed to prohibit binary options to retail investors and restrict CFDs with leverage limits, per-account margin close-out, negative balance protection, a ban on incentives and standardized risk warnings.
- lesson: Regulatory leverage caps exist because the structural edge in leveraged retail FX is against the client; treat any retail 'edge' claim with skepticism proportional to the leverage used.

### forex-034 - various majors (journal) (loss, verified=0, confidence=0.3)
- source: https://forums.babypips.com/t/chart-art-trading-journal-2023/1025099
- source_type: forum; tags: self-reported,retail,stop-loss,survivorship-bias
- what: A BabyPips member journaling their 2023 trading reports a run of losses while following a blog's chart trade ideas, admitting bad habits are catching up, including a trade with no stop loss.
- lesson: Self-reported retail results carry survivorship bias; even here the poster attributes losses to skipped stops, the classic failure mode, not to the strategy.

### forex-035 - various (first live account) (loss, verified=0, confidence=0.3)
- source: https://forums.babypips.com/t/traders-anonnymous-first-live-acount/20770
- source_type: forum; tags: self-reported,retail,stop-loss,survivorship-bias
- what: A BabyPips member's 'traders anonymous' confession describes blowing a first live account of $1000 over about four months, naming one culprit: not using a stop loss.
- lesson: The canonical retail loss is slow bleeding without stops, not one dramatic trade; self-report, treat as anecdote not evidence of rates.
