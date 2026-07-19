# FRED Ingestion Run — 2026-07-19

**Result: PASS**

- Series attempted: **60**
- OK: **60** · Empty: **0** · Errors: **0**
- Total observations loaded: **167,233**
- History start: 2005-01-01
- Duration: 36.5s

## All series

| Series | Name | Category | Status | Obs | First | Last |
|---|---|---|---|---|---|---|
| `M2SL` | US M2 money supply | conditions_liquidity | ok | 257 | 2005-01-01 | 2026-05-01 |
| `NFCI` | Chicago Fed financial conditions | conditions_liquidity | ok | 1123 | 2005-01-07 | 2026-07-10 |
| `STLFSI4` | St. Louis Fed financial stress | conditions_liquidity | ok | 1123 | 2005-01-07 | 2026-07-10 |
| `WALCL` | Fed balance sheet (total assets) | conditions_liquidity | ok | 1124 | 2005-01-05 | 2026-07-15 |
| `BAMLC0A0CM` | US IG corporate OAS | credit_spreads | ok | 786 | 2023-07-18 | 2026-07-16 |
| `BAMLC0A1CAAA` | US AAA OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLC0A2CAA` | US AA OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLC0A3CA` | US A OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLC0A4CBBB` | US BBB OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLEMCBPIOAS` | EM corporate OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLH0A0HYM2` | US HY corporate OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLH0A1HYBB` | US BB OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLH0A2HYB` | US B OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `BAMLH0A3HYC` | US CCC & lower OAS | credit_spreads | ok | 787 | 2023-07-18 | 2026-07-16 |
| `DEXUSEU` | USD per EUR | fx | ok | 5392 | 2005-01-03 | 2026-07-10 |
| `DEXUSUK` | USD per GBP | fx | ok | 5392 | 2005-01-03 | 2026-07-10 |
| `GDPC1` | US real GDP | growth | ok | 85 | 2005-01-01 | 2026-01-01 |
| `HOUST` | US housing starts | growth | ok | 258 | 2005-01-01 | 2026-06-01 |
| `ICSA` | US initial jobless claims | growth | ok | 1124 | 2005-01-01 | 2026-07-11 |
| `INDPRO` | US industrial production | growth | ok | 258 | 2005-01-01 | 2026-06-01 |
| `PAYEMS` | US nonfarm payrolls | growth | ok | 258 | 2005-01-01 | 2026-06-01 |
| `RSAFS` | US retail sales | growth | ok | 258 | 2005-01-01 | 2026-06-01 |
| `UMCSENT` | US consumer sentiment | growth | ok | 257 | 2005-01-01 | 2026-05-01 |
| `UNRATE` | US unemployment rate | growth | ok | 257 | 2005-01-01 | 2026-06-01 |
| `CPIAUCSL` | US CPI all items | inflation | ok | 257 | 2005-01-01 | 2026-06-01 |
| `CPILFESL` | US core CPI | inflation | ok | 257 | 2005-01-01 | 2026-06-01 |
| `PCEPILFE` | US core PCE | inflation | ok | 257 | 2005-01-01 | 2026-05-01 |
| `T10YIE` | US 10y breakeven inflation | inflation | ok | 5389 | 2005-01-03 | 2026-07-17 |
| `T5YIFR` | US 5y5y forward inflation | inflation | ok | 5389 | 2005-01-03 | 2026-07-17 |
| `CP0000EZ19M086NEST` | Euro area HICP (index) | intl_macro | ok | 258 | 2005-01-01 | 2026-06-01 |
| `GBRCPIALLMINMEI` | UK CPI all items (index) | intl_macro | ok | 243 | 2005-01-01 | 2025-03-01 |
| `LRHUTTTTEZM156S` | Euro area unemployment | intl_macro | ok | 217 | 2005-01-01 | 2023-01-01 |
| `LRHUTTTTGBM156S` | UK unemployment rate | intl_macro | ok | 254 | 2005-01-01 | 2026-02-01 |
| `NGDPRSAXDCGBQ` | UK real GDP | intl_macro | ok | 85 | 2005-01-01 | 2026-01-01 |
| `IRLTLT01DEM156N` | Germany 10y bund yield | intl_yields | ok | 258 | 2005-01-01 | 2026-06-01 |
| `IRLTLT01EZM156N` | Euro area 10y yield | intl_yields | ok | 253 | 2005-01-01 | 2026-01-01 |
| `IRLTLT01GBM156N` | UK 10y gilt yield | intl_yields | ok | 258 | 2005-01-01 | 2026-06-01 |
| `DFF` | US fed funds (effective) | policy_rates | ok | 7867 | 2005-01-01 | 2026-07-16 |
| `ECBDFR` | ECB deposit facility rate | policy_rates | ok | 7868 | 2005-01-01 | 2026-07-17 |
| `IUDSOIA` | UK SONIA (BoE policy proxy) | policy_rates | ok | 5440 | 2005-01-04 | 2026-07-15 |
| `DCOILBRENTEU` | Brent crude oil | risk_crossasset | ok | 5448 | 2005-01-04 | 2026-07-13 |
| `DCOILWTICO` | WTI crude oil | risk_crossasset | ok | 5401 | 2005-01-03 | 2026-07-13 |
| `DTWEXBGS` | Broad USD index | risk_crossasset | ok | 5144 | 2006-01-02 | 2026-07-10 |
| `VIXCLS` | VIX | risk_crossasset | ok | 5449 | 2005-01-03 | 2026-07-16 |
| `DFII10` | US 10y real yield (TIPS) | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DFII5` | US 5y real yield (TIPS) | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS1` | US 1-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS10` | US 10-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS1MO` | US 1-month | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS2` | US 2-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS20` | US 20-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS3` | US 3-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS30` | US 30-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS3MO` | US 3-month | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS5` | US 5-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS6MO` | US 6-month | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `DGS7` | US 7-year | us_treasury_curve | ok | 5388 | 2005-01-03 | 2026-07-16 |
| `T10Y2Y` | US 2s10s slope | us_treasury_curve | ok | 5389 | 2005-01-03 | 2026-07-17 |
| `T10Y3M` | US 3m10y slope (recession signal) | us_treasury_curve | ok | 5389 | 2005-01-03 | 2026-07-17 |
| `THREEFYTP10` | US 10y term premium (Kim-Wright) | us_treasury_curve | ok | 5384 | 2005-01-03 | 2026-07-10 |
