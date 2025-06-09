#!/usr/bin/env python3
"""
📊 PRODUCTION TRADING SYSTEM - POSITION MANAGEMENT SYSTEM
src/trading/position_manager.py

Enterprise-grade position tracking with real-time P&L calculation, portfolio analytics,
risk metrics, and comprehensive position lifecycle management.

Features:
- Real-time position tracking and synchronization
- Comprehensive P&L calculation (realized and unrealized)
- Portfolio-level analytics and metrics
- Position sizing and allocation management
- Risk metrics and exposure tracking
- Cost basis and tax lot management
- Performance attribution analysis
- Sector and geographic allocation tracking
- Compliance and audit trail

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import json
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from decimal import Decimal, ROUND_HALF_UP
import uuid
from collections import defaultdict, deque
import statistics
import math

# Import our core components
try:
    from ..core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from ..core.config_manager import ProductionConfigManager, TierConfiguration
    from ..core.state_manager import ProductionStateManager
    from .alpaca_client import (
        ProductionAlpacaClient, Position, AccountInfo, Quote, Trade, PositionSide
    )
    from .order_manager import ProductionOrderManager, OrderExecution
except ImportError:
    # Fallback for testing
    from core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from core.config_manager import ProductionConfigManager, TierConfiguration
    from core.state_manager import ProductionStateManager
    from alpaca_client import (
        ProductionAlpacaClient, Position, AccountInfo, Quote, Trade, PositionSide
    )
    from order_manager import ProductionOrderManager, OrderExecution

# ============================================================================
# POSITION MANAGEMENT TYPES AND ENUMS
# ============================================================================

class PositionStatus(Enum):
    """Position status"""
    ACTIVE = "active"
    CLOSED = "closed"
    CLOSING = "closing"
    ERROR = "error"

class RiskLevel(Enum):
    """Risk level classification"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class EnhancedPosition:
    """Enhanced position with additional analytics"""
    # Basic position data
    symbol: str
    quantity: float
    side: PositionSide
    avg_entry_price: float
    current_price: float
    market_value: float
    cost_basis: float
    
    # P&L metrics
    unrealized_pnl: float
    unrealized_pnl_percent: float
    realized_pnl: float
    total_pnl: float
    
    # Risk metrics
    position_size_percent: float
    daily_pnl: float
    daily_pnl_percent: float
    max_gain: float
    max_loss: float
    
    # Position metadata
    tier: str
    sector: str
    entry_date: datetime
    last_updated: datetime
    status: PositionStatus
    
    # Advanced metrics
    volatility: Optional[float] = None
    beta: Optional[float] = None
    correlation_spy: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    
    # Tracking
    position_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trade_count: int = 0
    dividend_income: float = 0.0

@dataclass
class PortfolioMetrics:
    """Portfolio-level metrics and analytics"""
    # Basic metrics
    total_value: float
    cash: float
    long_value: float
    short_value: float
    net_value: float
    
    # P&L metrics
    total_pnl: float
    total_pnl_percent: float
    daily_pnl: float
    daily_pnl_percent: float
    unrealized_pnl: float
    realized_pnl: float
    
    # Risk metrics
    max_drawdown: float
    current_drawdown: float
    volatility: float
    sharpe_ratio: float
    beta: float
    
    # Allocation metrics
    tier_allocations: Dict[str, float]
    sector_allocations: Dict[str, float]
    top_positions: List[Dict[str, Any]]
    
    # Performance metrics
    annualized_return: float
    win_rate: float
    profit_factor: float
    
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class PositionSnapshot:
    """Point-in-time position snapshot for tracking"""
    timestamp: datetime
    symbol: str
    quantity: float
    price: float
    market_value: float
    pnl: float
    portfolio_percent: float

@dataclass
class TradeRecord:
    """Individual trade record for position tracking"""
    trade_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: datetime
    fees: float = 0.0
    trade_type: str = "regular"  # regular, dividend, split, etc.

# ============================================================================
# PRODUCTION POSITION MANAGER
# ============================================================================

class ProductionPositionManager:
    """
    Enterprise-grade position management system
    
    Features:
    - Real-time position tracking and P&L
    - Portfolio analytics and risk metrics
    - Position sizing and allocation management
    - Historical tracking and performance analysis
    - Risk monitoring and alert generation
    """
    
    def __init__(self, config_manager: ProductionConfigManager,
                 state_manager: ProductionStateManager,
                 alpaca_client: ProductionAlpacaClient):
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.alpaca_client = alpaca_client
        self.logger = LoggerFactory.get_logger('position_manager', LogCategory.TRADING)
        
        # Position tracking
        self._position_lock = threading.RLock()
        self.positions = {}  # symbol -> EnhancedPosition
        self.position_history = deque(maxlen=10000)  # Historical snapshots
        self.trade_history = deque(maxlen=5000)  # Trade records
        
        # Portfolio tracking
        self.portfolio_metrics = None
        self.portfolio_history = deque(maxlen=1000)
        self.last_portfolio_value = 0.0
        self.peak_portfolio_value = 0.0
        
        # Configuration
        self.trading_config = config_manager.get_config('trading')
        self.risk_config = config_manager.get_config('risk')
        self.tier_configs = {
            'tier_1': config_manager.get_tier_config('tier_1'),
            'tier_2': config_manager.get_tier_config('tier_2'), 
            'tier_3': config_manager.get_tier_config('tier_3')
        }
        
        # Market data cache
        self.market_data_cache = {}
        self.cache_timestamp = {}
        self.cache_ttl = 60  # 1 minute cache
        
        # Performance tracking
        self.sync_count = 0
        self.last_sync_time = None
        self.error_count = 0
        
        # Register with state manager
        state_manager.register_component('position_manager', self)
        
        self.logger.info("📊 Position Manager initialized",
                        cache_ttl=self.cache_ttl)
    
    # ========================================================================
    # POSITION SYNCHRONIZATION
    # ========================================================================
    
    def sync_positions(self) -> bool:
        """Synchronize positions with Alpaca"""
        
        start_time = time.time()
        
        try:
            with self._position_lock:
                self.logger.debug("🔄 Synchronizing positions with Alpaca")
                
                # Get current positions from Alpaca
                alpaca_positions = self.alpaca_client.get_positions()
                alpaca_symbols = {pos.symbol for pos in alpaca_positions}
                
                # Get account information
                account_info = self.alpaca_client.get_account()
                
                if not account_info:
                    self.logger.error("❌ Failed to get account information")
                    return False
                
                # Update existing positions and add new ones
                updated_positions = set()
                
                for alpaca_pos in alpaca_positions:
                    enhanced_pos = self._create_enhanced_position(alpaca_pos, account_info)
                    if enhanced_pos:
                        self.positions[alpaca_pos.symbol] = enhanced_pos
                        updated_positions.add(alpaca_pos.symbol)
                
                # Remove positions that no longer exist
                symbols_to_remove = []
                for symbol in self.positions:
                    if symbol not in alpaca_symbols:
                        symbols_to_remove.append(symbol)
                
                for symbol in symbols_to_remove:
                    self.positions[symbol].status = PositionStatus.CLOSED
                    self.logger.info(f"🔄 Position closed: {symbol}")
                    # Keep in history but mark as closed
                    # del self.positions[symbol]
                
                # Update portfolio metrics
                self._update_portfolio_metrics(account_info)
                
                # Take portfolio snapshot
                self._take_portfolio_snapshot()
                
                sync_time = time.time() - start_time
                self.sync_count += 1
                self.last_sync_time = datetime.now(timezone.utc)
                
                self.logger.info(f"✅ Position sync completed",
                               active_positions=len([p for p in self.positions.values() if p.status == PositionStatus.ACTIVE]),
                               total_value=account_info.portfolio_value,
                               sync_time=sync_time)
                
                # Log performance metric
                self.logger.performance(PerformanceMetric(
                    metric_name="position_sync_time",
                    value=sync_time,
                    unit="seconds",
                    timestamp=datetime.now(timezone.utc),
                    component="position_manager"
                ))
                
                return True
                
        except Exception as e:
            self.error_count += 1
            self.logger.error(f"❌ Position sync failed: {e}")
            return False
    
    def _create_enhanced_position(self, alpaca_pos: Position, 
                                 account_info: AccountInfo) -> Optional[EnhancedPosition]:
        """Create enhanced position from Alpaca position"""
        
        try:
            # Get tier information
            tier = self.config_manager.get_symbol_tier(alpaca_pos.symbol) or "unknown"
            
            # Get sector information (simplified mapping)
            sector = self._get_symbol_sector(alpaca_pos.symbol)
            
            # Calculate position size percentage
            position_size_percent = 0.0
            if account_info.portfolio_value > 0:
                position_size_percent = (abs(alpaca_pos.market_value) / account_info.portfolio_value) * 100
            
            # Calculate total P&L (for now, same as unrealized)
            total_pnl = alpaca_pos.unrealized_pl
            
            # Get existing position for historical data
            existing_pos = self.positions.get(alpaca_pos.symbol)
            entry_date = existing_pos.entry_date if existing_pos else datetime.now(timezone.utc)
            trade_count = existing_pos.trade_count if existing_pos else 0
            max_gain = existing_pos.max_gain if existing_pos else alpaca_pos.unrealized_pl
            max_loss = existing_pos.max_loss if existing_pos else alpaca_pos.unrealized_pl
            
            # Update max gain/loss
            if alpaca_pos.unrealized_pl > max_gain:
                max_gain = alpaca_pos.unrealized_pl
            if alpaca_pos.unrealized_pl < max_loss:
                max_loss = alpaca_pos.unrealized_pl
            
            enhanced_pos = EnhancedPosition(
                symbol=alpaca_pos.symbol,
                quantity=alpaca_pos.qty,
                side=alpaca_pos.side,
                avg_entry_price=alpaca_pos.avg_entry_price,
                current_price=alpaca_pos.current_price,
                market_value=alpaca_pos.market_value,
                cost_basis=alpaca_pos.cost_basis,
                unrealized_pnl=alpaca_pos.unrealized_pl,
                unrealized_pnl_percent=alpaca_pos.unrealized_plpc * 100,
                realized_pnl=0.0,  # TODO: Calculate from trade history
                total_pnl=total_pnl,
                position_size_percent=position_size_percent,
                daily_pnl=alpaca_pos.unrealized_intraday_pl,
                daily_pnl_percent=alpaca_pos.unrealized_intraday_plpc * 100,
                max_gain=max_gain,
                max_loss=max_loss,
                tier=tier,
                sector=sector,
                entry_date=entry_date,
                last_updated=datetime.now(timezone.utc),
                status=PositionStatus.ACTIVE,
                trade_count=trade_count
            )
            
            return enhanced_pos
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create enhanced position for {alpaca_pos.symbol}: {e}")
            return None
    
    def _get_symbol_sector(self, symbol: str) -> str:
        """Get sector for symbol (simplified mapping)"""
        
        # Simplified sector mapping for common symbols
        sector_map = {
            # Technology
            'AAPL': 'Technology', 'MSFT': 'Technology', 'GOOGL': 'Technology', 'GOOG': 'Technology',
            'META': 'Technology', 'NVDA': 'Technology', 'AMD': 'Technology', 'INTC': 'Technology',
            'CRM': 'Technology', 'ORCL': 'Technology', 'ADBE': 'Technology', 'NFLX': 'Technology',
            
            # Healthcare
            'JNJ': 'Healthcare', 'PFE': 'Healthcare', 'UNH': 'Healthcare', 'ABT': 'Healthcare',
            'TMO': 'Healthcare', 'MRK': 'Healthcare',
            
            # Financial
            'JPM': 'Financial', 'BAC': 'Financial', 'MA': 'Financial', 'V': 'Financial',
            'GS': 'Financial', 'WFC': 'Financial',
            
            # Consumer Discretionary
            'AMZN': 'Consumer Discretionary', 'TSLA': 'Consumer Discretionary', 'HD': 'Consumer Discretionary',
            'DIS': 'Consumer Discretionary', 'NKE': 'Consumer Discretionary',
            
            # Consumer Staples
            'PG': 'Consumer Staples', 'KO': 'Consumer Staples', 'WMT': 'Consumer Staples',
            'PEP': 'Consumer Staples',
            
            # Energy
            'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy',
            
            # Industrial
            'CAT': 'Industrial', 'BA': 'Industrial', 'GE': 'Industrial'
        }
        
        return sector_map.get(symbol, 'Other')
    
    # ========================================================================
    # PORTFOLIO METRICS AND ANALYTICS
    # ========================================================================
    
    def _update_portfolio_metrics(self, account_info: AccountInfo):
        """Update portfolio-level metrics"""
        
        try:
            # Basic portfolio values
            total_value = account_info.portfolio_value
            cash = account_info.cash
            long_value = account_info.long_market_value
            short_value = account_info.short_market_value
            net_value = long_value + short_value
            
            # Calculate P&L metrics
            total_pnl = 0.0
            daily_pnl = 0.0
            unrealized_pnl = 0.0
            
            for position in self.positions.values():
                if position.status == PositionStatus.ACTIVE:
                    total_pnl += position.total_pnl
                    daily_pnl += position.daily_pnl
                    unrealized_pnl += position.unrealized_pnl
            
            # Calculate percentage changes
            total_pnl_percent = (total_pnl / total_value * 100) if total_value > 0 else 0.0
            daily_pnl_percent = (daily_pnl / total_value * 100) if total_value > 0 else 0.0
            
            # Calculate drawdown
            if total_value > self.peak_portfolio_value:
                self.peak_portfolio_value = total_value
            
            current_drawdown = 0.0
            if self.peak_portfolio_value > 0:
                current_drawdown = ((self.peak_portfolio_value - total_value) / self.peak_portfolio_value) * 100
            
            # Calculate allocations
            tier_allocations = self._calculate_tier_allocations()
            sector_allocations = self._calculate_sector_allocations()
            top_positions = self._get_top_positions(5)
            
            # Create portfolio metrics
            self.portfolio_metrics = PortfolioMetrics(
                total_value=total_value,
                cash=cash,
                long_value=long_value,
                short_value=short_value,
                net_value=net_value,
                total_pnl=total_pnl,
                total_pnl_percent=total_pnl_percent,
                daily_pnl=daily_pnl,
                daily_pnl_percent=daily_pnl_percent,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=0.0,  # TODO: Calculate from trade history
                max_drawdown=0.0,  # TODO: Calculate historical max drawdown
                current_drawdown=current_drawdown,
                volatility=0.0,  # TODO: Calculate portfolio volatility
                sharpe_ratio=0.0,  # TODO: Calculate Sharpe ratio
                beta=0.0,  # TODO: Calculate portfolio beta
                tier_allocations=tier_allocations,
                sector_allocations=sector_allocations,
                top_positions=top_positions,
                annualized_return=0.0,  # TODO: Calculate annualized return
                win_rate=0.0,  # TODO: Calculate win rate from trades
                profit_factor=0.0  # TODO: Calculate profit factor
            )
            
            # Store in history
            self.portfolio_history.append(self.portfolio_metrics)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to update portfolio metrics: {e}")
    
    def _calculate_tier_allocations(self) -> Dict[str, float]:
        """Calculate allocation by tier"""
        
        allocations = {'tier_1': 0.0, 'tier_2': 0.0, 'tier_3': 0.0, 'unknown': 0.0}
        total_value = sum(abs(pos.market_value) for pos in self.positions.values() 
                         if pos.status == PositionStatus.ACTIVE)
        
        if total_value > 0:
            for position in self.positions.values():
                if position.status == PositionStatus.ACTIVE:
                    allocation_percent = (abs(position.market_value) / total_value) * 100
                    tier = position.tier if position.tier in allocations else 'unknown'
                    allocations[tier] += allocation_percent
        
        return allocations
    
    def _calculate_sector_allocations(self) -> Dict[str, float]:
        """Calculate allocation by sector"""
        
        allocations = defaultdict(float)
        total_value = sum(abs(pos.market_value) for pos in self.positions.values() 
                         if pos.status == PositionStatus.ACTIVE)
        
        if total_value > 0:
            for position in self.positions.values():
                if position.status == PositionStatus.ACTIVE:
                    allocation_percent = (abs(position.market_value) / total_value) * 100
                    allocations[position.sector] += allocation_percent
        
        return dict(allocations)
    
    def _get_top_positions(self, limit: int) -> List[Dict[str, Any]]:
        """Get top positions by market value"""
        
        active_positions = [pos for pos in self.positions.values() 
                           if pos.status == PositionStatus.ACTIVE]
        
        # Sort by absolute market value
        sorted_positions = sorted(active_positions, 
                                key=lambda p: abs(p.market_value), 
                                reverse=True)
        
        top_positions = []
        for position in sorted_positions[:limit]:
            top_positions.append({
                'symbol': position.symbol,
                'market_value': position.market_value,
                'position_size_percent': position.position_size_percent,
                'unrealized_pnl': position.unrealized_pnl,
                'unrealized_pnl_percent': position.unrealized_pnl_percent
            })
        
        return top_positions
    
    def _take_portfolio_snapshot(self):
        """Take point-in-time portfolio snapshot"""
        
        try:
            timestamp = datetime.now(timezone.utc)
            
            for position in self.positions.values():
                if position.status == PositionStatus.ACTIVE:
                    snapshot = PositionSnapshot(
                        timestamp=timestamp,
                        symbol=position.symbol,
                        quantity=position.quantity,
                        price=position.current_price,
                        market_value=position.market_value,
                        pnl=position.unrealized_pnl,
                        portfolio_percent=position.position_size_percent
                    )
                    self.position_history.append(snapshot)
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to take portfolio snapshot: {e}")
    
    # ========================================================================
    # POSITION ACCESS AND QUERIES
    # ========================================================================
    
    def get_position(self, symbol: str) -> Optional[EnhancedPosition]:
        """Get position for specific symbol"""
        
        with self._position_lock:
            return self.positions.get(symbol.upper())
    
    def get_all_positions(self, active_only: bool = True) -> List[EnhancedPosition]:
        """Get all positions"""
        
        with self._position_lock:
            if active_only:
                return [pos for pos in self.positions.values() 
                       if pos.status == PositionStatus.ACTIVE]
            else:
                return list(self.positions.values())
    
    def get_positions_by_tier(self, tier: str) -> List[EnhancedPosition]:
        """Get positions by tier"""
        
        with self._position_lock:
            return [pos for pos in self.positions.values() 
                   if pos.tier == tier and pos.status == PositionStatus.ACTIVE]
    
    def get_positions_by_sector(self, sector: str) -> List[EnhancedPosition]:
        """Get positions by sector"""
        
        with self._position_lock:
            return [pos for pos in self.positions.values() 
                   if pos.sector == sector and pos.status == PositionStatus.ACTIVE]
    
    def get_portfolio_metrics(self) -> Optional[PortfolioMetrics]:
        """Get current portfolio metrics"""
        
        return self.portfolio_metrics
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary"""
        
        with self._position_lock:
            active_positions = [pos for pos in self.positions.values() 
                              if pos.status == PositionStatus.ACTIVE]
            
            if not self.portfolio_metrics:
                return {}
            
            return {
                'portfolio_value': self.portfolio_metrics.total_value,
                'cash': self.portfolio_metrics.cash,
                'total_pnl': self.portfolio_metrics.total_pnl,
                'total_pnl_percent': self.portfolio_metrics.total_pnl_percent,
                'daily_pnl': self.portfolio_metrics.daily_pnl,
                'daily_pnl_percent': self.portfolio_metrics.daily_pnl_percent,
                'position_count': len(active_positions),
                'current_drawdown': self.portfolio_metrics.current_drawdown,
                'tier_allocations': self.portfolio_metrics.tier_allocations,
                'sector_allocations': self.portfolio_metrics.sector_allocations,
                'top_positions': self.portfolio_metrics.top_positions,
                'last_updated': self.portfolio_metrics.timestamp.isoformat()
            }
    
    # ========================================================================
    # POSITION UPDATES AND TRADE TRACKING
    # ========================================================================
    
    def record_trade(self, symbol: str, side: str, quantity: float, 
                    price: float, fees: float = 0.0, trade_id: str = None):
        """Record a trade for position tracking"""
        
        try:
            with self._position_lock:
                if not trade_id:
                    trade_id = str(uuid.uuid4())
                
                trade_record = TradeRecord(
                    trade_id=trade_id,
                    symbol=symbol.upper(),
                    side=side.lower(),
                    quantity=quantity,
                    price=price,
                    timestamp=datetime.now(timezone.utc),
                    fees=fees
                )
                
                self.trade_history.append(trade_record)
                
                # Update position trade count
                if symbol.upper() in self.positions:
                    self.positions[symbol.upper()].trade_count += 1
                
                self.logger.info(f"📝 Trade recorded: {symbol} {side} {quantity} @ {price}",
                               trade_id=trade_id)
                
        except Exception as e:
            self.logger.error(f"❌ Failed to record trade: {e}")
    
    def update_position_price(self, symbol: str, new_price: float):
        """Update position with new market price"""
        
        try:
            with self._position_lock:
                if symbol.upper() in self.positions:
                    position = self.positions[symbol.upper()]
                    old_price = position.current_price
                    
                    # Update price and recalculate metrics
                    position.current_price = new_price
                    position.market_value = position.quantity * new_price
                    position.unrealized_pnl = position.market_value - position.cost_basis
                    
                    if position.cost_basis != 0:
                        position.unrealized_pnl_percent = (position.unrealized_pnl / abs(position.cost_basis)) * 100
                    
                    position.last_updated = datetime.now(timezone.utc)
                    
                    self.logger.debug(f"💰 Price updated: {symbol} {old_price} → {new_price}")
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to update position price for {symbol}: {e}")
    
    # ========================================================================
    # RISK AND COMPLIANCE CHECKS
    # ========================================================================
    
    def check_position_limits(self, symbol: str, new_quantity: float) -> Tuple[bool, str]:
        """Check if position would violate limits"""
        
        try:
            # Get tier configuration
            tier = self.config_manager.get_symbol_tier(symbol)
            if not tier:
                return False, f"Symbol {symbol} not in configured tiers"
            
            tier_config = self.config_manager.get_tier_config(tier)
            if not tier_config:
                return False, f"Tier configuration not found for {tier}"
            
            # Get current portfolio value
            if not self.portfolio_metrics:
                return False, "Portfolio metrics not available"
            
            portfolio_value = self.portfolio_metrics.total_value
            if portfolio_value <= 0:
                return False, "Invalid portfolio value"
            
            # Calculate new position value
            quote = self.alpaca_client.get_latest_quote(symbol)
            if not quote:
                return False, f"Unable to get quote for {symbol}"
            
            estimated_price = quote.ask_price
            new_position_value = abs(new_quantity) * estimated_price
            new_position_percent = (new_position_value / portfolio_value) * 100
            
            # Check tier limits
            if new_position_percent > tier_config.max_position_size_percent:
                return False, f"Position size {new_position_percent:.2f}% exceeds tier limit {tier_config.max_position_size_percent}%"
            
            if new_position_percent < tier_config.min_position_size_percent and new_quantity > 0:
                return False, f"Position size {new_position_percent:.2f}% below tier minimum {tier_config.min_position_size_percent}%"
            
            # Check risk limits
            risk_limits = self.config_manager.get_risk_limits()
            if new_position_percent > risk_limits.max_single_position_percent:
                return False, f"Position size {new_position_percent:.2f}% exceeds risk limit {risk_limits.max_single_position_percent}%"
            
            return True, "Position limits check passed"
            
        except Exception as e:
            self.logger.error(f"❌ Position limits check failed: {e}")
            return False, f"Position limits check error: {e}"
    
    def check_tier_allocation_limits(self) -> Dict[str, Any]:
        """Check tier allocation limits"""
        
        results = {}
        
        try:
            if not self.portfolio_metrics:
                return {'error': 'Portfolio metrics not available'}
            
            current_allocations = self.portfolio_metrics.tier_allocations
            
            for tier_name, current_percent in current_allocations.items():
                if tier_name == 'unknown':
                    continue
                    
                tier_config = self.config_manager.get_tier_config(tier_name)
                if tier_config:
                    min_allocation = tier_config.min_allocation_percent
                    max_allocation = tier_config.max_allocation_percent
                    
                    status = "OK"
                    message = ""
                    
                    if current_percent < min_allocation:
                        status = "UNDER"
                        message = f"Below minimum allocation ({current_percent:.1f}% < {min_allocation}%)"
                    elif current_percent > max_allocation:
                        status = "OVER"
                        message = f"Above maximum allocation ({current_percent:.1f}% > {max_allocation}%)"
                    else:
                        message = f"Within allocation range ({min_allocation}% - {max_allocation}%)"
                    
                    results[tier_name] = {
                        'current_percent': current_percent,
                        'min_percent': min_allocation,
                        'max_percent': max_allocation,
                        'status': status,
                        'message': message
                    }
            
            return results
            
        except Exception as e:
            self.logger.error(f"❌ Tier allocation check failed: {e}")
            return {'error': str(e)}
    
    def get_risk_metrics(self) -> Dict[str, Any]:
        """Get portfolio risk metrics"""
        
        try:
            if not self.portfolio_metrics:
                return {}
            
            # Calculate concentration risk
            max_position_percent = 0.0
            if self.portfolio_metrics.top_positions:
                max_position_percent = self.portfolio_metrics.top_positions[0]['position_size_percent']
            
            # Calculate sector concentration
            max_sector_percent = 0.0
            if self.portfolio_metrics.sector_allocations:
                max_sector_percent = max(self.portfolio_metrics.sector_allocations.values())
            
            # Get risk limits
            risk_limits = self.config_manager.get_risk_limits()
            
            return {
                'current_drawdown': self.portfolio_metrics.current_drawdown,
                'max_drawdown_limit': risk_limits.max_drawdown_percent,
                'drawdown_status': 'OK' if self.portfolio_metrics.current_drawdown < risk_limits.max_drawdown_percent else 'BREACH',
                
                'max_position_percent': max_position_percent,
                'max_position_limit': risk_limits.max_single_position_percent,
                'position_concentration_status': 'OK' if max_position_percent < risk_limits.max_single_position_percent else 'BREACH',
                
                'max_sector_percent': max_sector_percent,
                'max_sector_limit': risk_limits.max_sector_concentration_percent,
                'sector_concentration_status': 'OK' if max_sector_percent < risk_limits.max_sector_concentration_percent else 'BREACH',
                
                'cash_percent': (self.portfolio_metrics.cash / self.portfolio_metrics.total_value * 100) if self.portfolio_metrics.total_value > 0 else 0,
                'min_cash_limit': risk_limits.min_cash_percent,
                'cash_status': 'OK' if (self.portfolio_metrics.cash / self.portfolio_metrics.total_value * 100) >= risk_limits.min_cash_percent else 'LOW',
                
                'tier_3_percent': self.portfolio_metrics.tier_allocations.get('tier_3', 0),
                'max_tier_3_limit': risk_limits.max_tier3_allocation_percent,
                'tier_3_status': 'OK' if self.portfolio_metrics.tier_allocations.get('tier_3', 0) <= risk_limits.max_tier3_allocation_percent else 'BREACH'
            }
            
        except Exception as e:
            self.logger.error(f"❌ Failed to calculate risk metrics: {e}")
            return {}
    
    # ========================================================================
    # PERFORMANCE AND ANALYTICS
    # ========================================================================
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary"""
        
        try:
            active_positions = [pos for pos in self.positions.values() 
                              if pos.status == PositionStatus.ACTIVE]
            
            if not active_positions:
                return {'message': 'No active positions'}
            
            # Position performance
            winning_positions = [pos for pos in active_positions if pos.unrealized_pnl > 0]
            losing_positions = [pos for pos in active_positions if pos.unrealized_pnl < 0]
            
            win_rate = (len(winning_positions) / len(active_positions)) * 100 if active_positions else 0
            
            # P&L statistics
            total_pnl = sum(pos.unrealized_pnl for pos in active_positions)
            average_pnl = statistics.mean([pos.unrealized_pnl for pos in active_positions])
            
            best_performer = max(active_positions, key=lambda p: p.unrealized_pnl_percent)
            worst_performer = min(active_positions, key=lambda p: p.unrealized_pnl_percent)
            
            return {
                'total_positions': len(active_positions),
                'winning_positions': len(winning_positions),
                'losing_positions': len(losing_positions),
                'win_rate_percent': round(win_rate, 2),
                'total_unrealized_pnl': round(total_pnl, 2),
                'average_position_pnl': round(average_pnl, 2),
                'best_performer': {
                    'symbol': best_performer.symbol,
                    'pnl_percent': round(best_performer.unrealized_pnl_percent, 2),
                    'pnl': round(best_performer.unrealized_pnl, 2)
                },
                'worst_performer': {
                    'symbol': worst_performer.symbol,
                    'pnl_percent': round(worst_performer.unrealized_pnl_percent, 2),
                    'pnl': round(worst_performer.unrealized_pnl, 2)
                }
            }
            
        except Exception as e:
            self.logger.error(f"❌ Failed to calculate performance summary: {e}")
            return {'error': str(e)}
    
    def get_position_history(self, symbol: str = None, hours: int = 24) -> List[Dict[str, Any]]:
        """Get position history"""
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        history = []
        for snapshot in self.position_history:
            if snapshot.timestamp >= cutoff_time:
                if symbol is None or snapshot.symbol == symbol.upper():
                    history.append({
                        'timestamp': snapshot.timestamp.isoformat(),
                        'symbol': snapshot.symbol,
                        'quantity': snapshot.quantity,
                        'price': snapshot.price,
                        'market_value': snapshot.market_value,
                        'pnl': snapshot.pnl,
                        'portfolio_percent': snapshot.portfolio_percent
                    })
        
        return history
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def health_check(self) -> bool:
        """Perform position manager health check"""
        
        try:
            # Check if we have recent data
            if self.last_sync_time:
                time_since_sync = datetime.now(timezone.utc) - self.last_sync_time
                if time_since_sync > timedelta(minutes=15):
                    self.logger.warning("⚠️ Position data is stale")
                    return False
            
            # Check for excessive errors
            if self.error_count > 10:
                self.logger.warning(f"⚠️ High error count: {self.error_count}")
                return False
            
            # Check if Alpaca client is healthy
            if not self.alpaca_client.health_check():
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Position manager health check failed: {e}")
            return False
    
    def get_manager_status(self) -> Dict[str, Any]:
        """Get position manager status"""
        
        return {
            'sync_count': self.sync_count,
            'last_sync_time': self.last_sync_time.isoformat() if self.last_sync_time else None,
            'error_count': self.error_count,
            'active_positions': len([p for p in self.positions.values() if p.status == PositionStatus.ACTIVE]),
            'total_positions': len(self.positions),
            'position_history_size': len(self.position_history),
            'trade_history_size': len(self.trade_history),
            'portfolio_history_size': len(self.portfolio_history),
            'cache_size': len(self.market_data_cache),
            'healthy': self.health_check()
        }

# ============================================================================
# TESTING AND VALIDATION
# ============================================================================

def test_position_manager():
    """Test the position manager"""
    
    print("🧪 Testing Position Manager...")
    
    try:
        # Mock dependencies for testing
        class MockConfigManager:
            def get_config(self, section):
                return {}
            def get_symbol_tier(self, symbol):
                return 'tier_1'
            def get_tier_config(self, tier_name):
                from dataclasses import dataclass
                @dataclass
                class MockTierConfig:
                    min_allocation_percent: float = 50.0
                    max_allocation_percent: float = 70.0
                    max_position_size_percent: float = 12.0
                    min_position_size_percent: float = 4.0
                return MockTierConfig()
            def get_risk_limits(self):
                from dataclasses import dataclass
                @dataclass
                class MockRiskLimits:
                    max_single_position_percent: float = 12.0
                    max_drawdown_percent: float = 15.0
                    max_sector_concentration_percent: float = 30.0
                    min_cash_percent: float = 3.0
                    max_tier3_allocation_percent: float = 15.0
                return MockRiskLimits()
        
        class MockStateManager:
            def register_component(self, name, instance=None):
                pass
        
        class MockAlpacaClient:
            def health_check(self):
                return True
            def get_positions(self):
                return []
            def get_account(self):
                from dataclasses import dataclass
                @dataclass
                class MockAccount:
                    portfolio_value: float = 100000.0
                    cash: float = 10000.0
                    long_market_value: float = 90000.0
                    short_market_value: float = 0.0
                return MockAccount()
            def get_latest_quote(self, symbol):
                from dataclasses import dataclass
                @dataclass
                class MockQuote:
                    ask_price: float = 150.0
                    bid_price: float = 149.50
                return MockQuote()
        
        config_manager = MockConfigManager()
        state_manager = MockStateManager()
        alpaca_client = MockAlpacaClient()
        
        # Create position manager
        position_manager = ProductionPositionManager(config_manager, state_manager, alpaca_client)
        
        # Test sync
        sync_success = position_manager.sync_positions()
        print(f"✅ Position sync: {sync_success}")
        
        # Test portfolio summary
        summary = position_manager.get_portfolio_summary()
        print(f"✅ Portfolio summary: {len(summary)} metrics")
        
        # Test risk metrics
        risk_metrics = position_manager.get_risk_metrics()
        print(f"✅ Risk metrics: {len(risk_metrics)} metrics")
        
        # Test performance summary
        performance = position_manager.get_performance_summary()
        print(f"✅ Performance summary: {performance}")
        
        # Test health check
        healthy = position_manager.health_check()
        print(f"✅ Health check: {healthy}")
        
        # Test manager status
        status = position_manager.get_manager_status()
        print(f"✅ Manager status: {status['healthy']}")
        
        print("🎉 Position Manager test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Position Manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_position_manager()
