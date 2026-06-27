import duckdb
from pathlib import Path

Path("data").mkdir(exist_ok=True)

# Open (creates if missing) the warehouse file
con = duckdb.connect("data/warehouse.duckdb")

# Create a tiny table and put one row in it
con.execute("CREATE TABLE IF NOT EXISTS hello (msg VARCHAR, n INTEGER)")
con.execute("INSERT INTO hello VALUES ('warehouse is alive', 1)")

# Read it back
print(con.execute("SELECT * FROM hello").fetchall())
con.close()
print("Smoke test passed.")