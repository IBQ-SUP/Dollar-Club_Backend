from lumibot.strategies.strategy import Strategy
from lumibot.traders import Trader
from lumibot.entities import Asset, Order, TradingFee
from lumibot.credentials import IS_BACKTESTING
from lumibot.components.options_helper import OptionsHelper
from datetime import timedelta
import math

"""
Short Strangle Strategy
----------------------
This strategy sells an out-of-the-money (OTM) call and an OTM put on SPY to
collect option premium (“short strangle”).

How it works – plain-English overview
1. Each day the bot checks whether it already holds any open option positions.
2. If no positions are open, it looks ~30 calendar days into the future for
   the next available option expiration (using live option chains).
3. It then selects strikes roughly 5 % above (call) and 5 % below (put) the
   current SPY price.  Those strikes are adjusted to the closest ones that
   really exist in the chain so we do not request non-existent strikes.
4. One contract of each option is SOLD (creating premium income).  Because
   this is a short position we use SELL_TO_OPEN.
5. A few days before expiration the bot buys both legs back (BUY_TO_CLOSE) to
   avoid assignment risk.
6. The logic repeats, so there is usually a single short strangle on the
   books at any time.

Safety features
•  If option price data is missing the bot skips trading for the day.
•  Positions are exited three days before expiration to reduce early-exercise
   risk.

This code was generated based on the user prompt: 'please make trading bot(Short strangle strategy). I'm going to backtest with polygon. please give the python code'
"""

class ShortStrangleStrategy(Strategy):
    # Parameters show what can be tweaked without touching code
    parameters = {
        "underlying_symbol": "SPY",    # stock/ETF we trade options on
        "dte_target": 30,               # target “days-to-expiration” when opening
        "strike_buffer_pct": 0.05,      # ±5 % OTM strikes
        "contracts": 1,                 # how many call + put to sell
        "exit_days_before_exp": 3       # close before expiry when this close
    }

    def initialize(self):
        # Run once at start – set trading rhythm & helpers
        self.sleeptime = "1D"             # run once a day
        self.underlying_asset = Asset(self.parameters["underlying_symbol"],
                                      asset_type=Asset.AssetType.STOCK)
        # Options helper simplifies chain look-ups & order creation
        self.options_helper = OptionsHelper(self)
        # 24/7 not needed – stock options follow regular market hours.

    # ------------------------------------------------------------
    # Core daily logic – check positions & open new strangle if flat
    # ------------------------------------------------------------
    def on_trading_iteration(self):
        dt = self.get_datetime()
        self.log_message(f"Running daily check – {dt.date()}")

        # Filter out USD position so we only see actual option legs
        open_option_positions = [p for p in self.get_positions()
                                 if p.asset.asset_type == Asset.AssetType.OPTION]

        # --------------------------------------------------------
        # 1) If a position exists, make sure we exit in time
        # --------------------------------------------------------
        if open_option_positions:
            # All short strangle legs share the same expiry – just inspect first
            expiry_date = open_option_positions[0].asset.expiration
            days_to_exp = (expiry_date - dt.date()).days
            self.log_message(f"Existing strangle – {days_to_exp} DTE remaining")

            # If we are close to expiration exit to avoid assignment
            if days_to_exp <= self.parameters["exit_days_before_exp"]:
                self.log_message("Closing strangle before expiration", color="yellow")
                for pos in open_option_positions:
                    # BUY_TO_CLOSE offsets our earlier short sale
                    qty = abs(pos.quantity)  # quantity is negative for shorts
                    order = self.create_order(pos.asset,
                                              qty,
                                              Order.OrderSide.BUY_TO_CLOSE)
                    self.submit_order(order)
                # Add a marker for clarity on chart
                self.add_marker("Close Strangle", color="blue",
                                symbol="star", detail_text="Exiting before expiry")
            return  # Nothing else to do today

        # --------------------------------------------------------
        # 2) If no open strangle, build a new one
        # --------------------------------------------------------
        self.open_new_strangle()

    # Helper that builds & submits a short strangle
    def open_new_strangle(self):
        dt = self.get_datetime()
        underlying_price = self.get_last_price(self.underlying_asset)
        if underlying_price is None:
            self.log_message("Price unavailable – skipping today", color="red")
            return

        # Add line so we can see price trend on chart
        self.add_line(self.underlying_asset.symbol, underlying_price,
                      color="black", width=2, detail_text="Underlying price")

        # ----------------------------------------------------
        # 1) Find suitable expiration (≈ target DTE but must exist)
        # ----------------------------------------------------
        target_dte = self.parameters["dte_target"]
        preferred_exp = dt + timedelta(days=target_dte)

        chains = self.get_chains(self.underlying_asset)
        if not chains:
            self.log_message("Option chains unavailable", color="red")
            return

        expiry_date = self.options_helper.get_expiration_on_or_after_date(
            preferred_exp, chains, "call")
        if expiry_date is None:
            self.log_message("No valid expiration found – skipping", color="red")
            return
        expiry_str = expiry_date.strftime("%Y-%m-%d")

        # ----------------------------------------------------
        # 2) Determine strikes ±strike_buffer_pct away & snap to real strikes
        # ----------------------------------------------------
        buffer_pct = self.parameters["strike_buffer_pct"]
        approx_call_strike = underlying_price * (1 + buffer_pct)
        approx_put_strike = underlying_price * (1 - buffer_pct)

        # Real strikes set – separate for calls & puts
        call_chain = chains.get("Chains", {}).get("CALL", {})
        put_chain = chains.get("Chains", {}).get("PUT", {})
        call_strikes_list = call_chain.get(expiry_str)
        put_strikes_list = put_chain.get(expiry_str)
        if call_strikes_list is None or put_strikes_list is None:
            self.log_message("Strike lists missing for selected expiry", color="red")
            return

        # Choose closest available strike
        call_strike = min(call_strikes_list,
                          key=lambda s: abs(s - approx_call_strike))
        put_strike = min(put_strikes_list,
                         key=lambda s: abs(s - approx_put_strike))

        # ----------------------------------------------------
        # 3) Build option Asset objects
        # ----------------------------------------------------
        call_asset = Asset(self.underlying_asset.symbol,
                           asset_type=Asset.AssetType.OPTION,
                           expiration=expiry_date,
                           strike=call_strike,
                           right=Asset.OptionRight.CALL)
        put_asset = Asset(self.underlying_asset.symbol,
                          asset_type=Asset.AssetType.OPTION,
                          expiration=expiry_date,
                          strike=put_strike,
                          right=Asset.OptionRight.PUT)

        # ----------------------------------------------------
        # 4) Submit sell orders (short positions)
        # ----------------------------------------------------
        contracts = self.parameters["contracts"]
        orders = []
        orders.append(self.create_order(call_asset,
                                        contracts,
                                        Order.OrderSide.SELL_TO_OPEN))
        orders.append(self.create_order(put_asset,
                                        contracts,
                                        Order.OrderSide.SELL_TO_OPEN))
        self.submit_orders(orders)

        # Visual marker so we see when a new strangle is opened
        self.add_marker("Open Strangle", color="green", symbol="arrow-down",
                        detail_text=f"Sold {contracts}× {put_strike}-{call_strike}")
        self.log_message(f"Opened short strangle: sold {contracts}x {put_strike}P / {call_strike}C expiring {expiry_str}",
                         color="green")

    # ------------------------------------------------------------
    # Optional – when orders fill we can log for transparency
    # ------------------------------------------------------------
    def on_filled_order(self, position, order, price, quantity, multiplier):
        self.log_message(f"Order filled: {order.side} {quantity} {position.asset}")


# ============================================================
# MAIN – choose backtesting vs. live automatically
# ============================================================
if __name__ == "__main__":

    if IS_BACKTESTING:
        # ---------------- BACKTESTING PATH -----------------
        from lumibot.backtesting import PolygonDataBacktesting

        # Small commission assumption – $1 per option contract side
        option_fee = TradingFee(flat_fee=1.0)

        results = ShortStrangleStrategy.backtest(
            datasource_class=PolygonDataBacktesting,            # must use Polygon for options
            benchmark_asset=Asset("SPY", Asset.AssetType.STOCK),
            buy_trading_fees=[option_fee],
            sell_trading_fees=[option_fee],
            quote_asset=Asset("USD", Asset.AssetType.FOREX),
            parameters=ShortStrangleStrategy.parameters,
            budget=100000  # default $100K starting capital
        )
    else:
        # ---------------- LIVE TRADING PATH ----------------
        trader = Trader()  # Broker handled by LumiBot env vars
        strategy = ShortStrangleStrategy(
            quote_asset=Asset("USD", Asset.AssetType.FOREX))
        trader.add_strategy(strategy)
        trader.run_all()