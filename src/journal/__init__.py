"""
The Investment Journal layer: turns the platform from a market/screening dashboard
into an actual hypothetical-trading journal.

    src.journal.ledger            read/write data/journal/trades.csv (the only file
                                   that ever touches the CSV directly)
    src.journal.scan_candidates   read-only: rank fct_security_factors, print top N
    src.journal.add_trade         interactive: confirm a pick, append a trade row

Nothing here is a brokerage integration - it is a paper book for testing decision
quality against data the platform already tracks. See reports/Journal_Portfolio_Build_Plan.md.
"""
