import os
if "IB_USERNAME" not in os.environ:
    os.environ["IB_USERNAME"] = ""  # Prevents dotenv from overriding by default (override=False)
if "IB_PASSWORD" not in os.environ:
    os.environ["IB_PASSWORD"] = ""
if "IB_ACCOUNT_ID" not in os.environ:
    os.environ["IB_ACCOUNT_ID"] = ""

from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset, Order
from lumibot.components.options_helper import OptionsHelper

from datetime import timedelta

# We now use PostgreSQL instead of SQLite -----------------------------
try:
    import psycopg2                              # industry-standard PostgreSQL driver
    from psycopg2.extras import execute_values   # handy helper for fast INSERTs
except ImportError:
    raise ImportError("psycopg2 is required for PostgreSQL logging – make sure it is installed (pip install psycopg2-binary)")

class WheelOptionStrategy(Strategy):
    # ---------------------------------------------------------------------
    # INITIAL SET-UP
    # ---------------------------------------------------------------------
    def initialize(self):
        # One iteration per trading day is enough for the Wheel
        self.sleeptime = "1D"

        # Underlying stock/ETF we run the Wheel on
        self.underlying_asset = Asset(self.parameters.get("symbol"), Asset.AssetType.STOCK)

        # Helper for option chain look-ups
        self.options_helper = OptionsHelper(self)

        # Wheel “phase” tracker (PUT cycle vs. CALL cycle)
        if not hasattr(self.vars, "cycle"):
            self.vars.cycle = None

        # --------------------------------------------------------------
        # Database initialisation (only runs once per bot start-up)
        # --------------------------------------------------------------
        if not self.is_backtesting:
            self._setup_db()

    # ------------------------------------------------------------------
    # MAIN LOOP – executed every trading iteration (daily)
    # ------------------------------------------------------------------
    def on_trading_iteration(self):
        dt = self.get_datetime()
        self.log_message(f"===== Wheel check for {dt.date()} =====", color="blue")

        # Plot the current underlying price so it appears on the chart
        last_price = self.get_last_price(self.underlying_asset)
        if last_price is None:
            self.log_message("Price unavailable for underlying – will try again next iteration.", color="red")
            return
        self.add_line(self.underlying_asset.symbol, last_price, color="black", width=2, detail_text="Last Price")

        # --------------------------------------------------------------
        # STEP 1 – What do we already hold?
        # --------------------------------------------------------------
        equity_position = self.get_position(self.underlying_asset)
        shares_owned = equity_position.quantity if equity_position else 0

        # Check if we already have an option open on this underlying
        option_positions = [
            p for p in self.get_positions()
            if p.asset.asset_type == Asset.AssetType.OPTION and p.asset.symbol == self.underlying_asset.symbol
        ]
        if option_positions:
            self.log_message("Existing option position found – waiting until it is closed or expires.")
            return  # Do nothing else until that leg is finished

        # --------------------------------------------------------------
        # STEP 2 – Decide which leg to sell next
        # --------------------------------------------------------------
        if shares_owned < 100:
            self.log_message("<100 shares held – will try to SELL a cash-secured PUT.")
            self._sell_cash_secured_put(dt, last_price)
            self.vars.cycle = "cash_put"
        else:
            self.log_message(f"Holding {shares_owned} shares – will try to SELL a covered CALL.")
            self._sell_covered_call(dt, last_price, shares_owned)
            self.vars.cycle = "covered_call"

    # ------------------------------------------------------------------
    # HELPER to pick an expiry within the desired DTE window
    # ------------------------------------------------------------------
    def _select_expiration(self, dt, right: str):
        """Return a *date* for the chosen option expiry or None if none fit."""
        dte_min, dte_max = self.parameters.get("dteMin"), self.parameters.get("dteMax")

        chains_res = self.get_chains(self.underlying_asset)
        if not chains_res or "Chains" not in chains_res:
            self.log_message("Could not retrieve option chains – skipping trade.", color="red")
            return None

        target_dt_min = (dt + timedelta(days=dte_min)).date()
        target_dt_max = (dt + timedelta(days=dte_max)).date()

        expiry_candidate = self.options_helper.get_expiration_on_or_after_date(target_dt_min, chains_res, right)
        if expiry_candidate is None or expiry_candidate > target_dt_max:
            self.log_message("No suitable expiration found in desired DTE window.", color="yellow")
            return None
        return expiry_candidate

    # ------------------------------------------------------------------
    # ACTION:  Sell a cash-secured PUT
    # ------------------------------------------------------------------
    def _sell_cash_secured_put(self, dt, last_price):
        expiry = self._select_expiration(dt, "put")
        if expiry is None:
            return

        target_delta = -abs(self.parameters.get("targetDelta"))  # Puts are negative delta
        strike = self.options_helper.find_strike_for_delta(
            underlying_asset=self.underlying_asset,
            underlying_price=last_price,
            target_delta=target_delta,
            expiry=expiry,
            right=Asset.OptionRight.PUT,
        )
        if strike is None:
            self.log_message("Could not find strike matching target delta for PUT.", color="yellow")
            return

        cash_needed = strike * 100 * self.parameters.get("contracts")
        cash_available = self.get_cash()
        if cash_available < cash_needed:
            self.log_message(
                f"Not enough cash (${cash_available:,.2f}) for cash-secured PUT requiring ${cash_needed:,.2f}.",
                color="yellow",
            )
            return

        option_put = Asset(
            symbol=self.underlying_asset.symbol,
            asset_type=Asset.AssetType.OPTION,
            expiration=expiry,
            strike=strike,
            right=Asset.OptionRight.PUT,
            multiplier=100,
            underlying_asset=self.underlying_asset,  # avoids NoneType crash
        )
        qty = self.parameters.get("contracts")
        order = self.create_order(option_put, qty, Order.OrderSide.SELL_TO_OPEN)
        self.submit_order(order)
        self.log_message(f"Placed order: SELL_TO_OPEN {qty} {option_put}.", color="green")
        self.add_marker("Sold PUT", last_price, color="orange", symbol="arrow-down", size=8,
                         detail_text=f"{strike}p exp {expiry}")

    # ------------------------------------------------------------------
    # ACTION:  Sell a covered CALL
    # ------------------------------------------------------------------
    def _sell_covered_call(self, dt, last_price, shares_owned):
        expiry = self._select_expiration(dt, "call")
        if expiry is None:
            return

        target_delta = abs(self.parameters.get("target_delta"))  # Calls use positive delta
        strike = self.options_helper.find_strike_for_delta(
            underlying_asset=self.underlying_asset,
            underlying_price=last_price,
            target_delta=target_delta,
            expiry=expiry,
            right=Asset.OptionRight.CALL,
        )
        if strike is None:
            self.log_message("Could not find strike matching target delta for CALL.", color="yellow")
            return

        max_contracts = shares_owned // 100
        desired_contracts = min(max_contracts, self.parameters.get("contracts"))
        if desired_contracts == 0:
            self.log_message("Not enough shares to cover a contract.")
            return

        option_call = Asset(
            symbol=self.underlying_asset.symbol,
            asset_type=Asset.AssetType.OPTION,
            expiration=expiry,
            strike=strike,
            right=Asset.OptionRight.CALL,
            multiplier=100,
            underlying_asset=self.underlying_asset,
        )
        order = self.create_order(option_call, desired_contracts, Order.OrderSide.SELL_TO_OPEN)
        self.submit_order(order)
        self.log_message(f"Placed order: SELL_TO_OPEN {desired_contracts} {option_call}.", color="green")
        self.add_marker("Sold CALL", last_price, color="purple", symbol="arrow-up", size=8,
                         detail_text=f"{strike}c exp {expiry}")

    # ------------------------------------------------------------------
    # ORDER / POSITION CALLBACKS – these fire automatically
    # ------------------------------------------------------------------
    def on_new_order(self, order: Order):
        # Fired when an order is *accepted* by the broker
        self._insert_trade_log(order, status="NEW")

    def on_partially_filled_order(self, position, order, price, quantity, multiplier):
        # Fired each partial fill – we log it so fills can be reconstructed exactly
        self._insert_trade_log(order, status="PARTIAL_FILL", price=price, quantity=quantity)

    def on_filled_order(self, position, order, price, quantity, multiplier):
        # Fired when an order is completely filled
        self._insert_trade_log(order, status="FILLED", price=price, quantity=quantity)

    def on_canceled_order(self, order: Order):
        self._insert_trade_log(order, status="CANCELED")

    def on_abrupt_closing(self):
        # Make sure DB connection is closed cleanly on shutdown
        if hasattr(self.vars, "pg_conn") and self.vars.pg_conn:
            self.vars.pg_conn.close()
            self.log_message("PostgreSQL connection closed.")

    # ------------------------------------------------------------------
    # SMALL HELPERS:  PostgreSQL handling
    # ------------------------------------------------------------------
    def _setup_db(self):
        """Create table (and new columns if needed) then store connection in self.vars.pg_conn"""
        env = {k: os.getenv(k) for k in [
            "PG_HOST", "PG_PORT", "PG_DATABASE", "PG_USER", "PG_PASSWORD", "PG_SSLMODE"]}

        missing = [k for k, v in env.items() if k != "PG_SSLMODE" and (v is None or v == "")]
        if missing:
            self.log_message(
                f"PostgreSQL logging disabled – missing env vars: {', '.join(missing)}",
                color="yellow")
            self.vars.pg_conn = None
            return

        try:
            conn = psycopg2.connect(
                host=env["PG_HOST"],
                port=env["PG_PORT"],
                dbname=env["PG_DATABASE"],
                user=env["PG_USER"],
                password=env["PG_PASSWORD"],
                sslmode=env.get("PG_SSLMODE", "prefer"),
            )
            conn.autocommit = True  # ensures each INSERT is saved immediately
            self.vars.pg_conn = conn
            table_name = "trades"
            with conn.cursor() as cur:
                # Create table with the expanded schema if it doesn't exist yet
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
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
                    )""")
            # Attempt to add missing columns (safe to run every start-up)
            self._ensure_columns(conn, table_name)
            self.log_message(f"PostgreSQL logging enabled – writing to table '{table_name}'.", color="green")
        except Exception as e:
            self.log_message(f"ERROR connecting to PostgreSQL – logging disabled: {e}", color="red")
            self.vars.pg_conn = None

    @staticmethod
    def _ensure_columns(conn, table_name):
        """Try to add any new columns that might be missing (idempotent)."""
        columns_to_add = [
            ("option_right", "TEXT"),
            ("expiration", "DATE"),
            ("strike", "DOUBLE PRECISION"),
            ("multiplier", "INTEGER"),
            ("trade_value", "DOUBLE PRECISION"),
        ]
        with conn.cursor() as cur:
            for col, col_type in columns_to_add:
                try:
                    cur.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col} {col_type}")
                except Exception:
                    pass  # Ignore if it fails – maybe due to permissions

    # ------------------------------------------------------------------
    # Trade-event logging helper
    # ------------------------------------------------------------------
    def _insert_trade_log(self, order: Order, status: str, price=None, quantity=None):
        """Insert a single trade-event row; silently ignore if DB unavailable

        EXTRA INFORMATION ADDED:
            • option_right – "CALL" / "PUT" so you know which kind of option.
            • expiration   – option expiry date (NULL for stock trades).
            • strike       – option strike (NULL for stock trades).
            • multiplier   – 100 for US equity options, 1 for stock, etc.
            • trade_value  – signed cash amount (positive = cash in, negative = cash out).
        """
        conn = getattr(self.vars, "pg_conn", None)
        if conn is None:
            return  # Logging disabled or connection failed

        table_name = "trades"
        order_id = order.identifier or getattr(order, "id", "N/A")  # Some brokers use .id internally

        # Work out asset details
        asset = order.asset if order.asset else None
        asset_type = getattr(asset, "asset_type", "unknown") if asset else "unknown"
        option_right = getattr(asset, "right", None) if asset_type == Asset.AssetType.OPTION else None
        expiration = getattr(asset, "expiration", None) if asset_type == Asset.AssetType.OPTION else None
        strike = getattr(asset, "strike", None) if asset_type == Asset.AssetType.OPTION else None
        multiplier = getattr(asset, "multiplier", 1)

        # Quantity: for stock it is shares; for options it is # contracts
        qty = float(quantity if quantity is not None else order.quantity or 0)

        # Price can be None for NEW / CANCELED events – leave as NULL in DB
        px = float(price) if price is not None else None

        # ----------------------------------------------------------
        # Calculate signed trade value for PnL analysis
        #   Positive  = cash *in* (we sold something)
        #   Negative  = cash *out* (we bought/opened)
        #   NEW/CANCELED set to NULL because no money changed hands
        # ----------------------------------------------------------
        trade_value = None
        if status in {"PARTIAL_FILL", "FILLED"} and px is not None:
            # Options are quoted per share, so multiply by 100 (or multiplier)
            gross = px * qty * multiplier
            # Decide sign based on side (BUY* → negative; SELL* → positive)
            if str(order.side).lower().startswith("buy"):
                trade_value = -gross
            else:  # sell family (SELL, SELL_TO_OPEN, etc.)
                trade_value = gross

        record = (
            self.parameters.get("bot_id"),
            self.get_datetime(),  # event_timestamp
            order_id,
            asset.symbol if asset else "N/A",
            asset_type,
            option_right,
            expiration,
            strike,
            multiplier,
            order.side,
            qty,
            px,
            trade_value,
            status,
        )

        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {table_name} (bot_id, event_timestamp, order_id, symbol, asset_type, option_right, expiration, strike, multiplier, side, quantity, price, trade_value, status)\n VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    record,
                )
        except Exception as e:
            # If something goes wrong, disable future logging to avoid spamming errors
            self.log_message(f"PostgreSQL INSERT failed – logging disabled: {e}", color="red")
            self.vars.pg_conn = None
