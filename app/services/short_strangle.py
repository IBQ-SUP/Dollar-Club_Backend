from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset, Order
from lumibot.components.options_helper import OptionsHelper
from datetime import timedelta, datetime
import os

# Try to import psycopg2 for PostgreSQL logging. If unavailable we will warn and skip DB writes.
try:
    import psycopg2
except Exception:
    psycopg2 = None

"""
Short Strangle Strategy with PostgreSQL trade logging
---------------------------------------------------
This code was refined based on the user prompt: 'I only need these fields... please upgrade'

The strategy sells OTM call and put options on SPY (a short strangle) and closes them a few days before expiry.
This upgraded version records every order/event into a PostgreSQL table using only the specific columns requested by the user.
"""


class PostgresLogger:
    """Simple helper to insert trades and order events into PostgreSQL.

    The connection is read from environment variables: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

    If any variable is missing or psycopg2 is not installed, logging to DB is skipped and the bot continues to run.
    """

    # Modified table schema to exactly match the user's requested fields
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS trades (
        bot_id TEXT,
        event_timestamp TIMESTAMP,
        order_id TEXT,
        symbol TEXT,
        asset_type TEXT,
        option_right TEXT,
        expiration DATE,
        strike DOUBLE PRECISION,
        multiplier INTEGER,
        side TEXT,
        quantity DOUBLE PRECISION,
        price DOUBLE PRECISION,
        trade_value DOUBLE PRECISION,
        status TEXT
    );
    """

    def __init__(self, strategy=None):
        self.strategy = strategy
        self.conn = None
        self.enabled = False
        # Gather credentials from environment -- do not hardcode
        host = os.getenv("PG_HOST")
        port = os.getenv("PG_PORT")
        user = os.getenv("PG_USER")
        password = os.getenv("PG_PASSWORD")
        database = os.getenv("PG_DATABASE")

        if not psycopg2:
            if self.strategy is not None:
                self.strategy.log_message("psycopg2 not installed; PostgreSQL logging disabled", color="yellow")
            return

        if not (host and user and password and database):
            if self.strategy is not None:
                self.strategy.log_message("Postgres env vars missing; PostgreSQL logging disabled", color="yellow")
            return

        try:
            self.conn = psycopg2.connect(host=host, port=port or 5432, user=user, password=password, dbname=database)
            self.conn.autocommit = True
            self._create_table()
            self.enabled = True
            if self.strategy is not None:
                self.strategy.log_message("PostgreSQL logging enabled", color="green")
        except Exception as e:
            if self.strategy is not None:
                self.strategy.log_message(f"Could not connect to Postgres: {e}; DB logging disabled", color="red")
            self.conn = None
            self.enabled = False

    def _create_table(self):
        # Create the table if it doesn't exist (uses the simplified schema)
        with self.conn.cursor() as cur:
            cur.execute(self.CREATE_TABLE_SQL)

    def _serialize_order(self, order):
        # Convert order object into the reduced set of fields requested by the user
        try:
            asset = getattr(order, "asset", None)
            asset_symbol = None
            asset_type = None
            option_right = None
            strike = None
            expiration = None
            multiplier = None

            if asset is not None:
                asset_symbol = getattr(asset, "symbol", None)
                asset_type = getattr(asset, "asset_type", None)
                # Option specific
                option_right = getattr(asset, "right", None)
                strike = getattr(asset, "strike", None)
                exp = getattr(asset, "expiration", None)
                multiplier = getattr(asset, "multiplier", None) or None
                if exp is not None:
                    # expiration might be date or datetime
                    if isinstance(exp, datetime):
                        expiration = exp.date()
                    else:
                        expiration = exp

            qty = getattr(order, "quantity", None)
            # Choose price information in order of preference: avg_fill_price, limit_price, None
            price = getattr(order, "avg_fill_price", None) or getattr(order, "limit_price", None) or None

            # Compute trade value where possible: price * quantity * multiplier
            trade_value = None
            try:
                if price is not None and qty is not None:
                    # multiplier can be None; default to 1 in calculation
                    m = int(multiplier) if multiplier is not None else 1
                    trade_value = float(price) * float(qty) * float(m)
            except Exception:
                trade_value = None

            data = {
                "order_id": getattr(order, "identifier", None) or getattr(order, "id", None),
                "symbol": asset_symbol,
                "asset_type": asset_type,
                "option_right": option_right,
                "expiration": expiration.isoformat() if expiration is not None else None,
                "strike": float(strike) if strike is not None else None,
                "multiplier": int(multiplier) if multiplier is not None else None,
                "side": getattr(order, "side", None),
                "quantity": float(qty) if qty is not None else None,
                "price": float(price) if price is not None else None,
                "trade_value": float(trade_value) if trade_value is not None else None,
                "status": getattr(order, "status", None)
            }
            return data
        except Exception:
            # Fall back to minimal info if serialization fails
            return {
                "order_id": getattr(order, "identifier", None) or getattr(order, "id", None),
                "symbol": getattr(getattr(order, "asset", None), "symbol", None),
                "status": getattr(order, "status", None)
            }

    def log_event(self, event_type: str, order=None, note: str = None):
        if not self.enabled or self.conn is None:
            return

        payload = None
        if order is not None:
            payload = self._serialize_order(order)
        else:
            payload = {"order_id": None, "symbol": None, "asset_type": None, "option_right": None, "expiration": None, "strike": None, "multiplier": None, "side": None, "quantity": None, "price": None, "trade_value": None, "status": None}

        # Insert into DB using only the requested columns. This replaces the previous fuller JSON payload.
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trades (bot_id, event_timestamp, order_id, symbol, asset_type, option_right, expiration, strike, multiplier, side, quantity, price, trade_value, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        self.parameters.get("bot_id"),
                        datetime.utcnow(),
                        payload.get("order_id"),
                        payload.get("symbol"),
                        payload.get("asset_type"),
                        payload.get("option_right"),
                        payload.get("expiration"),
                        payload.get("strike"),
                        payload.get("multiplier"),
                        payload.get("side"),
                        payload.get("quantity"),
                        payload.get("price"),
                        payload.get("trade_value"),
                        payload.get("status")
                    )
                )
        except Exception as e:
            if self.strategy is not None:
                self.strategy.log_message(f"Failed to write event to Postgres: {e}", color="red")


class ShortStrangleStrategy(Strategy):
    # Parameters that are adjustable without editing code
    parameters = {
        "underlying_symbol": "SPY",
        "dte_target": 30,
        "strike_buffer_pct": 0.05,
        "contracts": 1,
        "exit_days_before_exp": 3
    }

    def initialize(self):
        # Called once when the strategy starts. Keep it simple for traders who don't code.
        self.sleeptime = "1D"  # run daily
        # Asset we use to find options chains and prices
        self.underlying_asset = Asset(self.parameters["underlying_symbol"], asset_type=Asset.AssetType.STOCK)
        # Helper to find expirations and build option orders
        self.options_helper = OptionsHelper(self)
        # Setup PostgreSQL logger (it will gracefully disable itself if DB config is missing)
        self.pg_logger = PostgresLogger(self)
        # Small persistent variable to avoid repeated logs in the same day
        if not hasattr(self.vars, "last_trade_date"):
            self.vars.last_trade_date = None

    def on_trading_iteration(self):
        # This runs once per day. Non-technical explanation: check positions; if none open, attempt to open a short strangle.
        dt = self.get_datetime()
        self.log_message(f"Daily check for short strangle – {dt.date()}")

        # Collect open option positions (ignore cash and stocks)
        open_option_positions = [p for p in self.get_positions() if p.asset.asset_type == Asset.AssetType.OPTION]

        # If we have options open, check DTE and close if within the safety window
        if open_option_positions:
            expiry_date = open_option_positions[0].asset.expiration
            days_to_exp = (expiry_date - dt.date()).days
            self.log_message(f"Existing strangle detected: {days_to_exp} days to expiry")

            if days_to_exp <= self.parameters["exit_days_before_exp"]:
                self.log_message("Exiting strangle to reduce assignment risk", color="yellow")
                for pos in open_option_positions:
                    # Create a buy-to-close order that offsets our short position
                    qty = abs(pos.quantity)
                    order = self.create_order(pos.asset, qty, Order.OrderSide.BUY_TO_CLOSE)
                    # Submit and let lifecycle methods capture the event
                    self.submit_order(order)
                    # Log the intention to database using the reduced schema
                    self.pg_logger.log_event("exit_initiated", order=order, note="Closing before expiry")
                # Mark the event on the chart
                self.add_marker("Close Strangle", self.get_last_price(self.underlying_asset), color="blue", symbol="star", detail_text="Closed before expiry")
            return

        # If flat, open a new strangle (but only once per day to avoid duplicate submissions)
        if self.vars.last_trade_date == dt.date():
            self.log_message("Already attempted trade today; skipping to avoid duplicates")
            return

        self.open_new_strangle()
        self.vars.last_trade_date = dt.date()

    def open_new_strangle(self):
        # Non-technical: find a good expiry and strikes about 5% away, adjust to available strikes, then sell one call & one put.
        dt = self.get_datetime()
        underlying_price = self.get_last_price(self.underlying_asset)
        if underlying_price is None:
            self.log_message("Underlying price not available; skipping trade for today", color="red")
            return

        # Add line for chart visibility so traders can see the underlying price
        self.add_line(self.underlying_asset.symbol, underlying_price, color="black", width=2, detail_text="Underlying price")

        # Choose a preferred expiration ~ DTE target days ahead
        target_dte = self.parameters["dte_target"]
        preferred_exp = dt + timedelta(days=target_dte)

        chains = self.get_chains(self.underlying_asset)
        if not chains:
            self.log_message("Option chains unavailable; skipping", color="red")
            return

        expiry_date = self.options_helper.get_expiration_on_or_after_date(preferred_exp, chains, "call")
        if expiry_date is None:
            self.log_message("No valid option expiration near target DTE; skipping", color="red")
            return
        expiry_str = expiry_date.strftime("%Y-%m-%d")

        buffer_pct = self.parameters["strike_buffer_pct"]
        approx_call_strike = underlying_price * (1 + buffer_pct)
        approx_put_strike = underlying_price * (1 - buffer_pct)

        call_chain = chains.get("Chains", {}).get("CALL", {})
        put_chain = chains.get("Chains", {}).get("PUT", {})
        call_strikes_list = call_chain.get(expiry_str)
        put_strikes_list = put_chain.get(expiry_str)
        if call_strikes_list is None or put_strikes_list is None:
            self.log_message("Strike lists missing for selected expiry; skipping", color="red")
            return

        # Choose the nearest real strike to our approx target
        call_strike = min(call_strikes_list, key=lambda s: abs(s - approx_call_strike))
        put_strike = min(put_strikes_list, key=lambda s: abs(s - approx_put_strike))

        # Build option asset objects using the real strikes/expiry
        call_asset = Asset(self.underlying_asset.symbol, asset_type=Asset.AssetType.OPTION, expiration=expiry_date, strike=call_strike, right=Asset.OptionRight.CALL)
        put_asset = Asset(self.underlying_asset.symbol, asset_type=Asset.AssetType.OPTION, expiration=expiry_date, strike=put_strike, right=Asset.OptionRight.PUT)

        # Prepare sell-to-open orders for both legs
        contracts = self.parameters["contracts"]
        call_order = self.create_order(call_asset, contracts, Order.OrderSide.SELL_TO_OPEN)
        put_order = self.create_order(put_asset, contracts, Order.OrderSide.SELL_TO_OPEN)

        # Before submitting check that we can get quote/pricing for both legs; if missing, skip the trade
        call_quote = self.get_quote(call_asset)
        put_quote = self.get_quote(put_asset)
        if call_quote is None or put_quote is None:
            self.log_message("Option quote data missing for one or both legs; skipping trade", color="red")
            return

        # Submit both orders together
        self.submit_orders([call_order, put_order])

        # Record these submissions to Postgres (intention) using the reduced schema
        self.pg_logger.log_event("open_initiated", order=call_order, note=f"Sold {contracts} call @{call_strike} exp {expiry_str}")
        self.pg_logger.log_event("open_initiated", order=put_order, note=f"Sold {contracts} put @{put_strike} exp {expiry_str}")

        # Chart marker and user-friendly log
        self.add_marker("Open Strangle", underlying_price, color="green", symbol="arrow-down", detail_text=f"Sold {contracts}x {put_strike}P / {call_strike}C")
        self.log_message(f"Submitted short strangle: sold {contracts}x {put_strike}P and {contracts}x {call_strike}C exp {expiry_str}", color="green")

    # Lifecycle handlers that help record events and provide trader-friendly messages
    def on_new_order(self, order: Order):
        # Called when an order is registered. We store the new order event in the DB.
        self.log_message(f"New order registered: {order.side} {getattr(order, 'quantity', '?')} {getattr(order.asset, 'symbol', '')}")
        # Log a registration event using the trimmed table design
        self.pg_logger.log_event("order_registered", order=order, note="Order registered by strategy")

    def on_filled_order(self, position, order, price, quantity, multiplier):
        # Called when an order fills. Non-technical: this records the fill and prints a simple message.
        self.log_message(f"Order filled: {order.side} {quantity} {position.asset.symbol} at {price}", color="blue")
        # Log fill to Postgres with helpful context (fill details will be captured by serializer)
        note = f"Filled at {price} qty {quantity} multiplier {multiplier}"
        self.pg_logger.log_event("order_filled", order=order, note=note)

    def on_canceled_order(self, order: Order):
        # Called when an order is canceled. Record that event too.
        self.log_message(f"Order canceled: {getattr(order, 'identifier', '')}", color="yellow")
        self.pg_logger.log_event("order_canceled", order=order, note="Order canceled")
