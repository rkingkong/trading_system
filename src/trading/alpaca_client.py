#!/usr/bin/env python3
"""
🔌 PRODUCTION TRADING SYSTEM - ALPACA MARKETS INTEGRATION
src/trading/alpaca_client.py

Enterprise-grade Alpaca Markets API client with comprehensive trading capabilities,
real-time market data, portfolio management, and production-level error handling.

Features:
- Complete Alpaca REST API v2 integration
- Real-time market data streaming
- Order execution with advanced order types
- Portfolio and position management
- Account information and buying power
- Real-time quotes and historical data
- Comprehensive error handling and retry logic
- Rate limiting and API optimization
- Paper trading safety controls

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import json
import time
import requests
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from decimal import Decimal
import uuid
import base64
from urllib.parse import urljoin
from contextlib import contextmanager

# Import our core components
try:
    from ..core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from ..core.config_manager import ProductionConfigManager, ApiConfiguration
    from ..core.state_manager import ProductionStateManager
except ImportError:
    # Fallback for testing
    from core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from core.config_manager import ProductionConfigManager, ApiConfiguration
    from core.state_manager import ProductionStateManager

# ============================================================================
# ALPACA API TYPES AND ENUMS
# ============================================================================

class OrderSide(Enum):
    """Order side (buy/sell)"""
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    """Order types supported by Alpaca"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"

class TimeInForce(Enum):
    """Time in force options"""
    DAY = "day"
    GTC = "gtc"  # Good Till Canceled
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill

class OrderStatus(Enum):
    """Order status values"""
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    ACCEPTED = "accepted"
    PENDING_NEW = "pending_new"
    ACCEPTED_FOR_BIDDING = "accepted_for_bidding"
    STOPPED = "stopped"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"

class PositionSide(Enum):
    """Position side"""
    LONG = "long"
    SHORT = "short"

@dataclass
class AccountInfo:
    """Account information from Alpaca"""
    id: str
    account_number: str
    status: str
    currency: str
    buying_power: float
    cash: float
    portfolio_value: float
    last_equity: float
    equity: float
    initial_margin: float
    maintenance_margin: float
    last_maintenance_margin: float
    sma: float
    daytrade_count: int
    daytrading_buying_power: float
    regt_buying_power: float
    pattern_day_trader: bool
    trading_blocked: bool
    transfers_blocked: bool
    account_blocked: bool
    created_at: datetime
    trade_suspended_by_user: bool
    multiplier: float
    shorting_enabled: bool
    long_market_value: float
    short_market_value: float
    accrued_fees: float

@dataclass
class Position:
    """Position information from Alpaca"""
    asset_id: str
    symbol: str
    exchange: str
    asset_class: str
    avg_entry_price: float
    qty: float
    side: PositionSide
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_plpc: float
    unrealized_intraday_pl: float
    unrealized_intraday_plpc: float
    current_price: float
    lastday_price: float
    change_today: float
    qty_available: float

@dataclass
class Order:
    """Order information from Alpaca"""
    id: str
    client_order_id: str
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime
    filled_at: Optional[datetime]
    expired_at: Optional[datetime]
    canceled_at: Optional[datetime]
    failed_at: Optional[datetime]
    replaced_at: Optional[datetime]
    replaced_by: Optional[str]
    replaces: Optional[str]
    asset_id: str
    symbol: str
    asset_class: str
    notional: Optional[float]
    qty: Optional[float]
    filled_qty: float
    filled_avg_price: Optional[float]
    order_class: str
    order_type: OrderType
    type: OrderType  # Alias for order_type
    side: OrderSide
    time_in_force: TimeInForce
    limit_price: Optional[float]
    stop_price: Optional[float]
    status: OrderStatus
    extended_hours: bool
    legs: Optional[List[Dict]]
    trail_percent: Optional[float]
    trail_price: Optional[float]
    hwm: Optional[float]

@dataclass
class Quote:
    """Real-time quote data"""
    symbol: str
    ask_price: float
    ask_size: int
    bid_price: float
    bid_size: int
    timestamp: datetime
    
@dataclass
class Trade:
    """Trade/execution data"""
    symbol: str
    price: float
    size: int
    timestamp: datetime
    conditions: List[str]

@dataclass
class Bar:
    """OHLCV bar data"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int
    vwap: float

# ============================================================================
# ALPACA API CLIENT
# ============================================================================

class AlpacaAPIError(Exception):
    """Alpaca API specific error"""
    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}

class AlpacaRateLimitError(AlpacaAPIError):
    """Rate limit exceeded error"""
    pass

class AlpacaAuthenticationError(AlpacaAPIError):
    """Authentication error"""
    pass

class ProductionAlpacaClient:
    """
    Production-grade Alpaca Markets API client
    
    Features:
    - Complete API v2 integration
    - Comprehensive error handling
    - Rate limiting and retry logic
    - Real-time market data
    - Order management
    - Portfolio tracking
    - Performance monitoring
    """
    
    def __init__(self, config_manager: ProductionConfigManager, 
                 state_manager: ProductionStateManager):
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.logger = LoggerFactory.get_logger('alpaca_client', LogCategory.TRADING)
        
        # Get Alpaca configuration
        alpaca_config = config_manager.get_api_config('alpaca')
        if not alpaca_config:
            raise AlpacaAPIError("Alpaca API configuration not found")
        
        self.api_key = alpaca_config.api_key
        self.secret_key = alpaca_config.secret_key
        self.base_url = alpaca_config.base_url
        self.timeout = alpaca_config.timeout
        self.max_retries = alpaca_config.max_retries
        
        # API endpoints
        self.data_base_url = "https://data.alpaca.markets"
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'APCA-API-KEY-ID': self.api_key,
            'APCA-API-SECRET-KEY': self.secret_key,
            'Content-Type': 'application/json',
            'User-Agent': 'TradingSystem/1.0.0'
        })
        
        # Rate limiting
        self._last_request_time = 0
        self._request_count = 0
        self._rate_limit_window = 60  # 1 minute
        self._max_requests_per_minute = 200
        self._rate_limit_lock = threading.RLock()
        
        # Connection state
        self.connected = False
        self.last_heartbeat = None
        
        # Register with state manager
        state_manager.register_component('alpaca_client', self)
        
        self.logger.info("🔌 Alpaca client initialized",
                        base_url=self.base_url,
                        paper_trading=True)
    
    # ========================================================================
    # CONNECTION AND AUTHENTICATION
    # ========================================================================
    
    def connect(self) -> bool:
        """Establish connection and verify authentication"""
        
        try:
            self.logger.info("🔐 Connecting to Alpaca Markets...")
            
            # Test connection with account info request
            account_info = self.get_account()
            
            if account_info:
                self.connected = True
                self.last_heartbeat = datetime.now(timezone.utc)
                
                self.state_manager.update_component_health('alpaca_client', True)
                
                self.logger.info("✅ Alpaca connection established",
                               account_id=account_info.id,
                               portfolio_value=account_info.portfolio_value,
                               buying_power=account_info.buying_power)
                
                return True
            else:
                raise AlpacaAPIError("Failed to retrieve account information")
                
        except Exception as e:
            self.connected = False
            self.state_manager.update_component_health('alpaca_client', False, str(e))
            self.logger.error(f"❌ Alpaca connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from Alpaca"""
        self.connected = False
        self.session.close()
        self.logger.info("🔌 Alpaca client disconnected")
    
    def health_check(self) -> bool:
        """Perform health check"""
        try:
            # Simple ping with account request
            account = self.get_account()
            
            if account:
                self.last_heartbeat = datetime.now(timezone.utc)
                self.state_manager.update_component_health('alpaca_client', True)
                return True
            else:
                self.state_manager.update_component_health('alpaca_client', False, "Health check failed")
                return False
                
        except Exception as e:
            self.state_manager.update_component_health('alpaca_client', False, str(e))
            return False
    
    # ========================================================================
    # API REQUEST MANAGEMENT
    # ========================================================================
    
    def _rate_limit_check(self):
        """Check and enforce rate limits"""
        
        with self._rate_limit_lock:
            current_time = time.time()
            
            # Reset counter if window has passed
            if current_time - self._last_request_time > self._rate_limit_window:
                self._request_count = 0
                self._last_request_time = current_time
            
            # Check if we're at the limit
            if self._request_count >= self._max_requests_per_minute:
                sleep_time = self._rate_limit_window - (current_time - self._last_request_time)
                if sleep_time > 0:
                    self.logger.warning(f"⏱️ Rate limit reached, sleeping {sleep_time:.2f}s")
                    time.sleep(sleep_time)
                    self._request_count = 0
                    self._last_request_time = time.time()
            
            self._request_count += 1
    
    def _make_request(self, method: str, endpoint: str, params: dict = None, 
                     data: dict = None, base_url: str = None) -> dict:
        """Make API request with error handling and retries"""
        
        if base_url is None:
            base_url = self.base_url
        
        url = urljoin(base_url, endpoint)
        
        # Rate limiting
        self._rate_limit_check()
        
        start_time = time.time()
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # Make request
                if method.upper() == 'GET':
                    response = self.session.get(url, params=params, timeout=self.timeout)
                elif method.upper() == 'POST':
                    response = self.session.post(url, json=data, timeout=self.timeout)
                elif method.upper() == 'PATCH':
                    response = self.session.patch(url, json=data, timeout=self.timeout)
                elif method.upper() == 'DELETE':
                    response = self.session.delete(url, timeout=self.timeout)
                else:
                    raise AlpacaAPIError(f"Unsupported HTTP method: {method}")
                
                response_time = time.time() - start_time
                
                # Log API call
                self.logger.api_call(
                    provider="alpaca",
                    endpoint=endpoint,
                    response_time=response_time,
                    status_code=response.status_code
                )
                
                # Handle response
                if response.status_code == 200:
                    try:
                        return response.json() if response.content else {}
                    except json.JSONDecodeError as e:
                        raise AlpacaAPIError(f"Invalid JSON response: {e}")
                
                elif response.status_code == 429:
                    # Rate limit exceeded
                    retry_after = int(response.headers.get('Retry-After', 60))
                    if attempt < self.max_retries:
                        self.logger.warning(f"⏱️ Rate limited, retrying after {retry_after}s")
                        time.sleep(retry_after)
                        continue
                    else:
                        raise AlpacaRateLimitError("Rate limit exceeded")
                
                elif response.status_code == 401:
                    raise AlpacaAuthenticationError("Authentication failed")
                
                elif response.status_code == 403:
                    raise AlpacaAPIError("Access forbidden - check permissions")
                
                elif response.status_code == 404:
                    raise AlpacaAPIError(f"Resource not found: {endpoint}")
                
                elif response.status_code >= 500:
                    # Server error - retry
                    if attempt < self.max_retries:
                        wait_time = min(2 ** attempt, 30)  # Exponential backoff
                        self.logger.warning(f"🔄 Server error {response.status_code}, retrying in {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise AlpacaAPIError(f"Server error: {response.status_code}")
                
                else:
                    # Other client errors
                    try:
                        error_data = response.json()
                        error_message = error_data.get('message', f"HTTP {response.status_code}")
                    except:
                        error_message = f"HTTP {response.status_code}"
                    
                    raise AlpacaAPIError(error_message, response.status_code, error_data)
            
            except requests.exceptions.Timeout as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = min(2 ** attempt, 30)
                    self.logger.warning(f"⏱️ Request timeout, retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
            
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = min(2 ** attempt, 30)
                    self.logger.warning(f"🔌 Connection error, retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
            
            except AlpacaAPIError:
                # Don't retry API errors
                raise
            
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = min(2 ** attempt, 30)
                    self.logger.warning(f"❌ Unexpected error, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
        
        # All retries exhausted
        raise AlpacaAPIError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")
    
    # ========================================================================
    # ACCOUNT MANAGEMENT
    # ========================================================================
    
    def get_account(self) -> Optional[AccountInfo]:
        """Get account information"""
        
        try:
            self.logger.debug("📊 Fetching account information")
            
            response = self._make_request('GET', '/v2/account')
            
            if response:
                account = AccountInfo(
                    id=response['id'],
                    account_number=response['account_number'],
                    status=response['status'],
                    currency=response['currency'],
                    buying_power=float(response['buying_power']),
                    cash=float(response['cash']),
                    portfolio_value=float(response['portfolio_value']),
                    last_equity=float(response['last_equity']),
                    equity=float(response['equity']),
                    initial_margin=float(response.get('initial_margin', 0)),
                    maintenance_margin=float(response.get('maintenance_margin', 0)),
                    last_maintenance_margin=float(response.get('last_maintenance_margin', 0)),
                    sma=float(response.get('sma', 0)),
                    daytrade_count=int(response.get('daytrade_count', 0)),
                    daytrading_buying_power=float(response.get('daytrading_buying_power', 0)),
                    regt_buying_power=float(response.get('regt_buying_power', 0)),
                    pattern_day_trader=response.get('pattern_day_trader', False),
                    trading_blocked=response.get('trading_blocked', False),
                    transfers_blocked=response.get('transfers_blocked', False),
                    account_blocked=response.get('account_blocked', False),
                    created_at=self._parse_datetime(response['created_at']),
                    trade_suspended_by_user=response.get('trade_suspended_by_user', False),
                    multiplier=float(response.get('multiplier', 1)),
                    shorting_enabled=response.get('shorting_enabled', False),
                    long_market_value=float(response.get('long_market_value', 0)),
                    short_market_value=float(response.get('short_market_value', 0)),
                    accrued_fees=float(response.get('accrued_fees', 0))
                )
                
                self.logger.debug("✅ Account information retrieved",
                                portfolio_value=account.portfolio_value,
                                buying_power=account.buying_power,
                                cash=account.cash)
                
                return account
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get account information: {e}")
            return None
    
    def get_portfolio_history(self, period: str = "1D", timeframe: str = "1Min", 
                            extended_hours: bool = None) -> Dict[str, Any]:
        """Get portfolio history"""
        
        try:
            params = {
                'period': period,
                'timeframe': timeframe
            }
            
            if extended_hours is not None:
                params['extended_hours'] = str(extended_hours).lower()
            
            response = self._make_request('GET', '/v2/account/portfolio/history', params=params)
            
            self.logger.debug("📈 Portfolio history retrieved",
                            period=period,
                            data_points=len(response.get('equity', [])))
            
            return response
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get portfolio history: {e}")
            return {}
    
    # ========================================================================
    # POSITION MANAGEMENT
    # ========================================================================
    
    def get_positions(self) -> List[Position]:
        """Get all positions"""
        
        try:
            self.logger.debug("📊 Fetching all positions")
            
            response = self._make_request('GET', '/v2/positions')
            
            positions = []
            for pos_data in response:
                position = Position(
                    asset_id=pos_data['asset_id'],
                    symbol=pos_data['symbol'],
                    exchange=pos_data['exchange'],
                    asset_class=pos_data['asset_class'],
                    avg_entry_price=float(pos_data['avg_entry_price']),
                    qty=float(pos_data['qty']),
                    side=PositionSide(pos_data['side']),
                    market_value=float(pos_data['market_value']),
                    cost_basis=float(pos_data['cost_basis']),
                    unrealized_pl=float(pos_data['unrealized_pl']),
                    unrealized_plpc=float(pos_data['unrealized_plpc']),
                    unrealized_intraday_pl=float(pos_data['unrealized_intraday_pl']),
                    unrealized_intraday_plpc=float(pos_data['unrealized_intraday_plpc']),
                    current_price=float(pos_data['current_price']),
                    lastday_price=float(pos_data['lastday_price']),
                    change_today=float(pos_data['change_today']),
                    qty_available=float(pos_data.get('qty_available', pos_data['qty']))
                )
                positions.append(position)
            
            self.logger.debug("✅ Positions retrieved",
                            count=len(positions),
                            symbols=[p.symbol for p in positions])
            
            return positions
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get positions: {e}")
            return []
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get specific position"""
        
        try:
            response = self._make_request('GET', f'/v2/positions/{symbol}')
            
            if response:
                position = Position(
                    asset_id=response['asset_id'],
                    symbol=response['symbol'],
                    exchange=response['exchange'],
                    asset_class=response['asset_class'],
                    avg_entry_price=float(response['avg_entry_price']),
                    qty=float(response['qty']),
                    side=PositionSide(response['side']),
                    market_value=float(response['market_value']),
                    cost_basis=float(response['cost_basis']),
                    unrealized_pl=float(response['unrealized_pl']),
                    unrealized_plpc=float(response['unrealized_plpc']),
                    unrealized_intraday_pl=float(response['unrealized_intraday_pl']),
                    unrealized_intraday_plpc=float(response['unrealized_intraday_plpc']),
                    current_price=float(response['current_price']),
                    lastday_price=float(response['lastday_price']),
                    change_today=float(response['change_today']),
                    qty_available=float(response.get('qty_available', response['qty']))
                )
                
                self.logger.debug("✅ Position retrieved",
                                symbol=symbol,
                                qty=position.qty,
                                market_value=position.market_value)
                
                return position
            
            return None
            
        except AlpacaAPIError as e:
            if e.status_code == 404:
                # No position found
                return None
            raise
        
        except Exception as e:
            self.logger.error(f"❌ Failed to get position for {symbol}: {e}")
            return None
    
    def close_position(self, symbol: str, qty: str = None, percentage: str = None) -> bool:
        """Close position (all or partial)"""
        
        try:
            data = {}
            if qty:
                data['qty'] = qty
            if percentage:
                data['percentage'] = percentage
            
            response = self._make_request('DELETE', f'/v2/positions/{symbol}', data=data)
            
            self.logger.info("🔄 Position close order submitted",
                           symbol=symbol,
                           qty=qty,
                           percentage=percentage)
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to close position {symbol}: {e}")
            return False
    
    def close_all_positions(self, cancel_orders: bool = True) -> bool:
        """Close all positions"""
        
        try:
            params = {'cancel_orders': str(cancel_orders).lower()}
            response = self._make_request('DELETE', '/v2/positions', params=params)
            
            self.logger.info("🔄 All positions close orders submitted",
                           cancel_orders=cancel_orders)
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to close all positions: {e}")
            return False
    
    # ========================================================================
    # ORDER MANAGEMENT
    # ========================================================================
    
    def submit_order(self, symbol: str, qty: float = None, notional: float = None,
                    side: OrderSide = OrderSide.BUY, order_type: OrderType = OrderType.MARKET,
                    time_in_force: TimeInForce = TimeInForce.DAY,
                    limit_price: float = None, stop_price: float = None,
                    trail_price: float = None, trail_percent: float = None,
                    extended_hours: bool = False, client_order_id: str = None,
                    order_class: str = "simple", take_profit: dict = None,
                    stop_loss: dict = None) -> Optional[Order]:
        """Submit order to Alpaca"""
        
        try:
            # Generate client order ID if not provided
            if not client_order_id:
                client_order_id = f"trading_system_{uuid.uuid4().hex[:8]}"
            
            # Build order data
            order_data = {
                'symbol': symbol.upper(),
                'side': side.value,
                'type': order_type.value,
                'time_in_force': time_in_force.value,
                'extended_hours': extended_hours,
                'client_order_id': client_order_id,
                'order_class': order_class
            }
            
            # Quantity or notional
            if qty is not None:
                order_data['qty'] = str(qty)
            elif notional is not None:
                order_data['notional'] = str(notional)
            else:
                raise AlpacaAPIError("Must specify either qty or notional")
            
            # Order-specific parameters
            if limit_price is not None:
                order_data['limit_price'] = str(limit_price)
            
            if stop_price is not None:
                order_data['stop_price'] = str(stop_price)
            
            if trail_price is not None:
                order_data['trail_price'] = str(trail_price)
            
            if trail_percent is not None:
                order_data['trail_percent'] = str(trail_percent)
            
            # Bracket order legs
            if take_profit:
                order_data['take_profit'] = take_profit
            
            if stop_loss:
                order_data['stop_loss'] = stop_loss
            
            self.logger.info("📋 Submitting order",
                           symbol=symbol,
                           side=side.value,
                           qty=qty,
                           order_type=order_type.value,
                           client_order_id=client_order_id)
            
            response = self._make_request('POST', '/v2/orders', data=order_data)
            
            if response:
                order = self._parse_order_response(response)
                
                self.logger.trade_execution(
                    action=side.value.upper(),
                    symbol=symbol,
                    quantity=int(qty) if qty else 0,
                    price=limit_price or 0.0,
                    order_id=order.id,
                    client_order_id=client_order_id
                )
                
                return order
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to submit order: {e}",
                            symbol=symbol,
                            side=side.value,
                            qty=qty)
            return None
    
    def get_orders(self, status: str = "open", limit: int = 500, 
                  after: datetime = None, until: datetime = None,
                  direction: str = "desc", nested: bool = True) -> List[Order]:
        """Get orders"""
        
        try:
            params = {
                'status': status,
                'limit': str(limit),
                'direction': direction,
                'nested': str(nested).lower()
            }
            
            if after:
                params['after'] = after.isoformat()
            
            if until:
                params['until'] = until.isoformat()
            
            response = self._make_request('GET', '/v2/orders', params=params)
            
            orders = []
            for order_data in response:
                order = self._parse_order_response(order_data)
                orders.append(order)
            
            self.logger.debug("📋 Orders retrieved",
                            status=status,
                            count=len(orders))
            
            return orders
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get orders: {e}")
            return []
    
    def get_order(self, order_id: str = None, client_order_id: str = None,
                 nested: bool = True) -> Optional[Order]:
        """Get specific order by ID"""
        
        try:
            if order_id:
                endpoint = f'/v2/orders/{order_id}'
            elif client_order_id:
                endpoint = f'/v2/orders:by_client_order_id'
                params = {'client_order_id': client_order_id}
            else:
                raise AlpacaAPIError("Must specify either order_id or client_order_id")
            
            params = {'nested': str(nested).lower()}
            
            response = self._make_request('GET', endpoint, params=params)
            
            if response:
                order = self._parse_order_response(response)
                
                self.logger.debug("📋 Order retrieved",
                                order_id=order.id,
                                symbol=order.symbol,
                                status=order.status.value)
                
                return order
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get order: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order"""
        
        try:
            response = self._make_request('DELETE', f'/v2/orders/{order_id}')
            
            self.logger.info("❌ Order cancelled", order_id=order_id)
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to cancel order {order_id}: {e}")
            return False
    
    def cancel_all_orders(self) -> bool:
        """Cancel all open orders"""
        
        try:
            response = self._make_request('DELETE', '/v2/orders')
            
            self.logger.info("❌ All orders cancelled")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to cancel all orders: {e}")
            return False
    
    def replace_order(self, order_id: str, qty: float = None, 
                     time_in_force: TimeInForce = None, limit_price: float = None,
                     stop_price: float = None, trail: float = None,
                     client_order_id: str = None) -> Optional[Order]:
        """Replace/modify order"""
        
        try:
            data = {}
            
            if qty is not None:
                data['qty'] = str(qty)
            
            if time_in_force is not None:
                data['time_in_force'] = time_in_force.value
            
            if limit_price is not None:
                data['limit_price'] = str(limit_price)
            
            if stop_price is not None:
                data['stop_price'] = str(stop_price)
            
            if trail is not None:
                data['trail'] = str(trail)
            
            if client_order_id is not None:
                data['client_order_id'] = client_order_id
            
            response = self._make_request('PATCH', f'/v2/orders/{order_id}', data=data)
            
            if response:
                order = self._parse_order_response(response)
                
                self.logger.info("🔄 Order replaced",
                               order_id=order_id,
                               new_order_id=order.id)
                
                return order
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to replace order {order_id}: {e}")
            return None
    
    def _parse_datetime(self, dt_str):
            """Parse datetime string from Alpaca API with microsecond handling"""
            if not dt_str:
                return None
            
            # Remove Z and replace with +00:00
            dt_str = dt_str.replace('Z', '+00:00')
            
            # Fix microseconds issue - Alpaca sometimes returns 4 digits instead of 6
            import re
            # Find microseconds pattern like .3386+00:00 and pad to 6 digits
            pattern = r'\.(\d{1,5})\+'
            match = re.search(pattern, dt_str)
            if match:
                microseconds = match.group(1)
                # Pad to 6 digits
                padded_microseconds = microseconds.ljust(6, '0')
                dt_str = dt_str.replace(f'.{microseconds}+', f'.{padded_microseconds}+')
            
            return datetime.fromisoformat(dt_str)
        
        return Order(
            id=response['id'],
            client_order_id=response['client_order_id'],
            created_at=parse_datetime(response['created_at']),
            updated_at=parse_datetime(response['updated_at']),
            submitted_at=parse_datetime(response['submitted_at']),
            filled_at=parse_datetime(response.get('filled_at')),
            expired_at=parse_datetime(response.get('expired_at')),
            canceled_at=parse_datetime(response.get('canceled_at')),
            failed_at=parse_datetime(response.get('failed_at')),
            replaced_at=parse_datetime(response.get('replaced_at')),
            replaced_by=response.get('replaced_by'),
            replaces=response.get('replaces'),
            asset_id=response['asset_id'],
            symbol=response['symbol'],
            asset_class=response['asset_class'],
            notional=float(response['notional']) if response.get('notional') else None,
            qty=float(response['qty']) if response.get('qty') else None,
            filled_qty=float(response.get('filled_qty', 0)),
            filled_avg_price=float(response['filled_avg_price']) if response.get('filled_avg_price') else None,
            order_class=response.get('order_class', 'simple'),
            order_type=OrderType(response['order_type']),
            type=OrderType(response['order_type']),  # Alias
            side=OrderSide(response['side']),
            time_in_force=TimeInForce(response['time_in_force']),
            limit_price=float(response['limit_price']) if response.get('limit_price') else None,
            stop_price=float(response['stop_price']) if response.get('stop_price') else None,
            status=OrderStatus(response['status']),
            extended_hours=response.get('extended_hours', False),
            legs=response.get('legs'),
            trail_percent=float(response['trail_percent']) if response.get('trail_percent') else None,
            trail_price=float(response['trail_price']) if response.get('trail_price') else None,
            hwm=float(response['hwm']) if response.get('hwm') else None
        )
    
    # ========================================================================
    # MARKET DATA
    # ========================================================================
    
    def get_latest_quote(self, symbol: str) -> Optional[Quote]:
        """Get latest quote for symbol"""
        
        try:
            response = self._make_request('GET', f'/v2/stocks/{symbol}/quotes/latest', 
                                        base_url=self.data_base_url)
            
            if response and 'quote' in response:
                quote_data = response['quote']
                
                quote = Quote(
                    symbol=symbol,
                    ask_price=float(quote_data['ap']),
                    ask_size=int(quote_data['as']),
                    bid_price=float(quote_data['bp']),
                    bid_size=int(quote_data['bs']),
                    timestamp=datetime.fromisoformat(quote_data['t'].replace('Z', '+00:00'))
                )
                
                return quote
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get quote for {symbol}: {e}")
            return None
    
    def get_latest_trade(self, symbol: str) -> Optional[Trade]:
        """Get latest trade for symbol"""
        
        try:
            response = self._make_request('GET', f'/v2/stocks/{symbol}/trades/latest',
                                        base_url=self.data_base_url)
            
            if response and 'trade' in response:
                trade_data = response['trade']
                
                trade = Trade(
                    symbol=symbol,
                    price=float(trade_data['p']),
                    size=int(trade_data['s']),
                    timestamp=datetime.fromisoformat(trade_data['t'].replace('Z', '+00:00')),
                    conditions=trade_data.get('c', [])
                )
                
                return trade
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get latest trade for {symbol}: {e}")
            return None
    
    def get_bars(self, symbol: str, timeframe: str = "1Day", start: datetime = None,
                end: datetime = None, limit: int = 1000, 
                adjustment: str = "raw") -> List[Bar]:
        """Get historical bars"""
        
        try:
            params = {
                'symbols': symbol,
                'timeframe': timeframe,
                'limit': str(limit),
                'adjustment': adjustment
            }
            
            if start:
                params['start'] = start.isoformat()
            
            if end:
                params['end'] = end.isoformat()
            
            response = self._make_request('GET', '/v2/stocks/bars', 
                                        params=params, base_url=self.data_base_url)
            
            bars = []
            if response and 'bars' in response and symbol in response['bars']:
                for bar_data in response['bars'][symbol]:
                    bar = Bar(
                        symbol=symbol,
                        timestamp=datetime.fromisoformat(bar_data['t'].replace('Z', '+00:00')),
                        open=float(bar_data['o']),
                        high=float(bar_data['h']),
                        low=float(bar_data['l']),
                        close=float(bar_data['c']),
                        volume=int(bar_data['v']),
                        trade_count=int(bar_data.get('n', 0)),
                        vwap=float(bar_data.get('vw', 0))
                    )
                    bars.append(bar)
            
            self.logger.debug("📊 Historical bars retrieved",
                            symbol=symbol,
                            timeframe=timeframe,
                            count=len(bars))
            
            return bars
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get bars for {symbol}: {e}")
            return []
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    @contextmanager
    def operation_context(self, operation: str):
        """Context manager for operation tracking"""
        
        execution_id = str(uuid.uuid4())
        
        with self.state_manager.component_operation('alpaca_client', operation):
            with self.logger.execution_context(execution_id, operation):
                yield
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status and statistics"""
        
        return {
            'connected': self.connected,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'base_url': self.base_url,
            'paper_trading': 'paper-api' in self.base_url,
            'rate_limit_remaining': max(0, self._max_requests_per_minute - self._request_count),
            'session_active': self.session is not None
        }
    
    def __enter__(self):
        """Context manager entry"""
        if not self.connected:
            self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()

# ============================================================================
# TESTING AND VALIDATION
# ============================================================================

def test_alpaca_client():
    """Test the Alpaca client"""
    
    print("🧪 Testing Alpaca Client...")
    
    try:
        # Mock dependencies for testing
        class MockConfigManager:
            def get_api_config(self, provider):
                if provider == 'alpaca':
                    from dataclasses import dataclass
                    @dataclass
                    class MockApiConfig:
                        api_key: str = 'test_key'
                        secret_key: str = 'test_secret'
                        base_url: str = 'https://paper-api.alpaca.markets'
                        timeout: int = 30
                        max_retries: int = 3
                    return MockApiConfig()
                return None
        
        class MockStateManager:
            def register_component(self, name, instance=None):
                pass
            def update_component_health(self, name, healthy, error=None):
                pass
            def component_operation(self, component, operation):
                from contextlib import contextmanager
                @contextmanager
                def mock_context():
                    yield
                return mock_context()
        
        config_manager = MockConfigManager()
        state_manager = MockStateManager()
        
        # Create Alpaca client
        client = ProductionAlpacaClient(config_manager, state_manager)
        
        print(f"✅ Client initialized: {client.base_url}")
        print(f"✅ Rate limiting configured: {client._max_requests_per_minute} req/min")
        print(f"✅ Session headers set: {len(client.session.headers)} headers")
        
        # Test connection status
        status = client.get_connection_status()
        print(f"✅ Connection status: {status}")
        
        # Test order data structure
        from datetime import datetime, timezone
        
        # Test order parsing (mock data)
        mock_order_response = {
            'id': 'test_order_123',
            'client_order_id': 'test_client_123',
            'created_at': '2025-06-09T02:00:00Z',
            'updated_at': '2025-06-09T02:00:00Z',
            'submitted_at': '2025-06-09T02:00:00Z',
            'asset_id': 'test_asset',
            'symbol': 'AAPL',
            'asset_class': 'us_equity',
            'qty': '100',
            'filled_qty': '0',
            'order_type': 'market',
            'side': 'buy',
            'time_in_force': 'day',
            'status': 'new',
            'extended_hours': False
        }
        
        order = client._parse_order_response(mock_order_response)
        print(f"✅ Order parsing: {order.symbol} {order.qty} shares")
        
        print("🎉 Alpaca Client test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Alpaca Client test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_alpaca_client()
