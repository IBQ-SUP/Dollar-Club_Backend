from datetime import timedelta
from decimal import Decimal
import os

from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset, Order
from lumibot.components.options_helper import OptionsHelper

# Optional dependency – only needed if the user provides Postgres credentials
try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    psycopg2 = None  # We handle the missing dependency gracefully later

# Numpy is OPTIONAL – we only import it if the user has it installed. This lets
# us recognise numpy.int64 / numpy.float64 and convert them to normal Python
try:
    import numpy as np
except ImportError:
    np = None

# -----------------------------------------------------------------------------
# Helper class – minimal wrapper around psycopg2 for logging orders
# -----------------------------------------------------------------------------
class PostgresLogger:
    """Lightweight helper that inserts order events into a Postgres table."""

    def __init__(self):
        # Read connection info from environment variables so there is **never**
        # a password hard-coded in the strategy.
        self.host = os.getenv("PG_HOST")
        self.port = os.getenv("PG_PORT", "5432")
        self.db   = os.getenv("PG_DATABASE")
        self.user = os.getenv("PG_USER")
        self.pwd  = os.getenv("PG_PASSWORD")

        # If any of these are missing we cannot log – warn the user once.
        if not all([self.host, self.db, self.user, self.pwd]):
            self.enabled = False
            print("[PostgresLogger] Environment variables incomplete – order logging disabled.")
            return

        if psycopg2 is None:
            self.enabled = False
            print("[PostgresLogger] psycopg2 not installed – order logging disabled.")
            return

        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.db,
                user=self.user,
                password=self.pwd,
            )
            self.conn.autocommit = True  # Simplifies inserts
            self._ensure_table()
            self.enabled = True
        except Exception as e:
            self.enabled = False
            print(f"[PostgresLogger] Could not connect to Postgres: {e}\nLogging disabled.")

    # ------------------------------------------------------------------
    def _ensure_table(self):
        """Create table if it does not exist."""
        create_sql = """
        CREATE TABLE IF NOT EXISTS trades (
            bot_id           TEXT,
            event_timestamp  TIMESTAMP,
            order_id         TEXT,
            symbol           TEXT,
            asset_type       TEXT,
            option_right     TEXT,
            expiration       DATE,
            strike           DOUBLE PRECISION,
            multiplier       INTEGER,
            side             TEXT,
            quantity         DOUBLE PRECISION,
            price            DOUBLE PRECISION,
            trade_value      DOUBLE PRECISION,
            status           TEXT
        );"""
        with self.conn.cursor() as cur:
            cur.execute(create_sql)

    # ------------------------------------------------------------------
    @staticmethod
    def _cast_postgres_safe(value):
        """Convert numpy & Decimal types into plain Python numbers (int/float)."""
        if value is None:
            return None

        # Handle numpy numbers
        if np is not None and isinstance(value, np.generic):
            return value.item()  # Convert to native Python scalar

        # Handle Decimal
        if isinstance(value, Decimal):
            return float(value)

        # psycopg2 can deal with int, float, str, datetime, date out of the box
        return value

    def log_event(self, rows):
        """Insert list of rows into Postgres – rows MUST match table columns order."""
        if not self.enabled or not rows:
            return

        # Sanitise every value in every row so psycopg2 never sees numpy types
        safe_rows = [tuple(self._cast_postgres_safe(v) for v in row) for row in rows]

        insert_sql = """
        INSERT INTO trades (
            bot_id, event_timestamp, order_id, symbol, asset_type, option_right,
            expiration, strike, multiplier, side, quantity, price, trade_value, status
        ) VALUES %s;"""
        try:
            with self.conn.cursor() as cur:
                execute_values(cur, insert_sql, safe_rows)
                # Optional: let the user know rows were saved – comment out if too noisy
                print(f"[PostgresLogger] ✅ Saved {len(safe_rows)} row(s) to Postgres.")
        except Exception as e:
            # Fail silently so trading logic is never blocked by DB hiccups
            print(f"[PostgresLogger] Failed to insert rows: {e}")

# -----------------------------------------------------------------------------
# Strategy
# -----------------------------------------------------------------------------
class ShortStraddleStrategy(Strategy):
    parameters = {
        "underlying_symbol": "SPY",
        "days_to_expiry": 7,
        "contracts": 1,      # number of option contracts (1 contract = 100 shares)
        "limit_type": "mid",
    }

    # -------------------------------------------------------------
    def initialize(self):
        self.sleeptime = "1D"  # Run once per trading day
        self.options_helper = OptionsHelper(self)
        # Draw the underlying price line so you can follow price action visually
        self.add_line(self.parameters["underlying_symbol"], 0, color="black", width=2, detail_text="Underlying Price")

        # --- Initialise Postgres logger (single instance) ---
        self.db_logger = PostgresLogger()
        if not self.db_logger.enabled:
            self.log_message("⚠️ Postgres logging disabled (check env vars / psycopg2)", color="yellow")

    # -------------------------------------------------------------
    def on_trading_iteration(self):
        dt = self.get_datetime()
        underlying_asset = Asset(self.parameters["underlying_symbol"], Asset.AssetType.STOCK)
        underlying_price = self.get_last_price(underlying_asset)
        if underlying_price is None:
            self.log_message("Price unavailable – skipping iteration", color="red")
            return

        # Update price line for the chart
        self.add_line(self.parameters["underlying_symbol"], underlying_price, color="black")

        # ------------------ Check existing straddle ------------------
        option_positions = [p for p in self.get_positions() if p.asset.asset_type == Asset.AssetType.OPTION]
        if option_positions:
            expiry_date = option_positions[0].asset.expiration
            days_to_exp = (expiry_date - dt.date()).days
            self.log_message(f"Existing straddle expires in {days_to_exp} day(s)")
            if days_to_exp <= 2:
                self.log_message("Closing existing straddle – within 2 days of expiration", color="yellow")
                closing_orders = []
                for pos in option_positions:
                    order = self.create_order(pos.asset, abs(pos.quantity), Order.OrderSide.BUY_TO_CLOSE)
                    closing_orders.append(order)
                self.submit_orders(closing_orders)
            return  # Either we closed or we keep holding – nothing else today

        # ------------------ Open a NEW straddle ----------------------
        chains_data = self.get_chains(underlying_asset)
        if not chains_data:
            self.log_message("Could not fetch option chains – skipping", color="red")
            return

        target_dt = dt + timedelta(days=self.parameters["days_to_expiry"])
        expiry_date = self.options_helper.get_expiration_on_or_after_date(target_dt, chains_data, "call")
        if expiry_date is None:
            self.log_message("No suitable expiration found – skipping", color="red")
            return

        expiry_str = expiry_date.strftime("%Y-%m-%d")
        call_chains = chains_data.get("Chains", {}).get("CALL", {})
        strikes = call_chains.get(expiry_str)
        if not strikes:
            self.log_message("No strikes available for chosen expiry – skipping", color="red")
            return

        atm_strike = self._find_liquid_atm_strike(strikes, underlying_price, expiry_date)
        if atm_strike is None:
            self.log_message("Could not find a liquid ATM strike with price data – skipping", color="red")
            return

        self.log_message(
            f"Opening new SHORT straddle: Exp {expiry_str} | Strike {atm_strike} | Underlying {underlying_price:.2f}",
            color="green",
        )

        # Build legs (1 CALL + 1 PUT) – we SELL TO OPEN each leg
        qty = self.parameters["contracts"]  # number of contracts per leg
        leg_orders = []
        for right in (Asset.OptionRight.CALL, Asset.OptionRight.PUT):
            option_asset = Asset(
                self.parameters["underlying_symbol"],
                asset_type=Asset.AssetType.OPTION,
                expiration=expiry_date,
                strike=atm_strike,
                right=right,
                multiplier=100,  # Option contracts control 100 shares
            )
            quote = self.get_quote(option_asset)
            limit_price = quote.mid_price if quote and quote.mid_price else None
            order = self.create_order(option_asset, qty, Order.OrderSide.SELL_TO_OPEN, limit_price=limit_price)
            leg_orders.append(order)

        self.submit_orders(leg_orders)
        # Visual cue on the chart
        self.add_marker("Short Straddle Opened", underlying_price, color="orange", symbol="star", size=10, detail_text=f"{expiry_str} @ {atm_strike}")

    # -------------------------------------------------------------
    def _find_liquid_atm_strike(self, strikes, underlying_price, expiry_date):
        """Pick the strike closest to the underlying price **with** price data for both call & put."""
        sorted_strikes = sorted(strikes, key=lambda s: abs(s - underlying_price))
        for strike in sorted_strikes:
            # Only look at strikes within ±5 % of spot – farther out usually illiquid
            if abs(strike - underlying_price) / underlying_price > 0.05:
                continue
            call_asset = Asset(self.parameters["underlying_symbol"], Asset.AssetType.OPTION, expiration=expiry_date, strike=strike, right=Asset.OptionRight.CALL)
            put_asset = Asset(self.parameters["underlying_symbol"], Asset.AssetType.OPTION, expiration=expiry_date, strike=strike, right=Asset.OptionRight.PUT)
            if self.get_last_price(call_asset) is not None and self.get_last_price(put_asset) is not None:
                return float(strike)  # Cast to plain float for safety
        return None

    # -------------------------------------------------------------
    # Order-event hooks – *all* events go to Postgres
    # -------------------------------------------------------------
    def _record_order(self, order: Order, status: str, price: float = None, quantity: float = None, multiplier: int = None, asset_override: Asset = None):
        """Formats and queues a single order-event row for Postgres."""
        if not self.db_logger.enabled:
            return

        asset = asset_override or order.asset if order else None
        if asset is None:
            return

        # Map asset fields safely
        option_right = getattr(asset, 'right', None) if asset.asset_type == Asset.AssetType.OPTION else None
        expiration   = getattr(asset, 'expiration', None) if asset.asset_type == Asset.AssetType.OPTION else None
        strike       = getattr(asset, 'strike', None) if asset.asset_type == Asset.AssetType.OPTION else None

        # Ensure native Python types – this prevents psycopg2 errors
        multiplier   = int(multiplier or getattr(asset, 'multiplier', 1) or 1)
        price        = float(price) if price is not None else 0.0
        quantity     = float(quantity) if quantity is not None else 0.0
        strike       = float(strike) if strike is not None else None

        trade_value  = price * quantity * multiplier if price and quantity else 0.0

        row = (
            self.parameters.get("bot_id"),
            self.get_datetime(),                                # event_timestamp – datetime
            getattr(order, "identifier", None) or getattr(order, "id", None) or "unknown",
            asset.symbol,                                       # symbol
            asset.asset_type,                                   # asset_type
            option_right,                                       # option_right (CALL/PUT)
            expiration,                                         # expiration (date)
            strike,                                             # strike (float)
            multiplier,                                         # multiplier (int)
            order.side,                                         # side (text)
            quantity,                                           # quantity (float)
            price,                                              # price (float)
            trade_value,                                        # trade_value (float)
            status,                                             # status (text)
        )
        self.db_logger.log_event([row])

    # -------------------------------------------------------------
    def on_new_order(self, order: Order):
        self._record_order(order, status="NEW")

    def on_partially_filled_order(self, position, order, price, quantity, multiplier):
        self._record_order(order, status="PARTIAL_FILL", price=price, quantity=quantity, multiplier=multiplier, asset_override=position.asset)

    def on_filled_order(self, position, order, price, quantity, multiplier):
        self._record_order(order, status="FILLED", price=price, quantity=quantity, multiplier=multiplier, asset_override=position.asset)
        self.log_message(f"Filled {order.side} {quantity} {position.asset.symbol} @ {price}", color="blue")

    def on_canceled_order(self, order: Order):
        self._record_order(order, status="CANCELED")

# -----------------------------------------------------------------------------
# Utility (outside the Strategy) – quick PnL calculation from the DB
# -----------------------------------------------------------------------------

def calculate_pnl_from_db():
    """Simple helper to demonstrate how you could calculate PnL from the trades table."""
    if psycopg2 is None:
        print("psycopg2 not installed – cannot compute PnL from DB")
        return

    try:
        conn = psycopg2.connect(
            host=os.getenv("PG_HOST"),
            port=os.getenv("PG_PORT", "5432"),
            dbname=os.getenv("PG_DATABASE"),
            user=os.getenv("PG_USER"),
            password=os.getenv("PG_PASSWORD"),
        )
        cur = conn.cursor()
        cur.execute("""SELECT symbol, side, SUM(trade_value) FROM trades WHERE status='FILLED' GROUP BY symbol, side""")
        rows = cur.fetchall()
        pnl_per_symbol = {}
        for symbol, side, total in rows:
            sign = -1 if "BUY" in side.upper() else 1  # Buys are cash outflow
            pnl_per_symbol[symbol] = pnl_per_symbol.get(symbol, 0) + sign * total
        total_pnl = sum(pnl_per_symbol.values())
        print("--------------  PnL Summary  ----------------")
        for sym, pnl in pnl_per_symbol.items():
            print(f"{sym}: {pnl:,.2f}")
        print("TOTAL PnL:", f"{total_pnl:,.2f}")
        cur.close(); conn.close()
    except Exception as e:
        print(f"Error computing PnL: {e}")
