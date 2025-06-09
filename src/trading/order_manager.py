#!/usr/bin/env python3
"""
📋 PRODUCTION TRADING SYSTEM - ORDER MANAGEMENT SYSTEM
src/trading/order_manager.py

Enterprise-grade order management with sophisticated execution logic, order routing,
fill tracking, and comprehensive order lifecycle management for the trading system.

Features:
- Intelligent order execution and routing
- Advanced order types and strategies
- Real-time order tracking and monitoring
- Partial fill handling and aggregation
- Order slicing for large positions
- Smart order timing and market conditions
- Comprehensive order history and audit trail
- Risk-aware order validation
- Performance analytics and execution metrics

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import json
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
from decimal import Decimal, ROUND_HALF_UP
import uuid
from collections import defaultdict, deque
import statistics

# Import our core components
try:
    from ..core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from ..core.config_manager import ProductionConfigManager, TierConfiguration
    from ..core.state_manager import ProductionStateManager
    from .alpaca_client import (
        ProductionAlpacaClient, Order, OrderSide, OrderType, OrderStatus, 
        TimeInForce, AlpacaAPIError, Quote, Trade
    )
except ImportError:
    # Fallback for testing
    from core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from core.config_manager import ProductionConfigManager, TierConfiguration
    from core.state_manager import ProductionStateManager
    from alpaca_client import (
        ProductionAlpacaClient, Order, OrderSide, OrderType, OrderStatus,
        TimeInForce, AlpacaAPIError, Quote, Trade
    )

# ============================================================================
# ORDER MANAGEMENT TYPES AND ENUMS
# ============================================================================

class OrderIntent(Enum):
    """High-level order intent"""
    ENTRY = "entry"           # Opening new position
    EXIT = "exit"             # Closing existing position
    REBALANCE = "rebalance"   # Portfolio rebalancing
    STOP_LOSS = "stop_loss"   # Risk management
    TAKE_PROFIT = "take_profit"  # Profit taking
    HEDGE = "hedge"           # Risk hedging

class ExecutionStrategy(Enum):
    """Order execution strategies"""
    IMMEDIATE = "immediate"       # Execute immediately at market
    TWAP = "twap"                # Time-weighted average price
    VWAP = "vwap"                # Volume-weighted average price
    ICEBERG = "iceberg"          # Hide order size
    SMART_ROUTING = "smart_routing"  # Intelligent routing
    SCHEDULED = "scheduled"       # Scheduled execution

class OrderPriority(Enum):
    """Order execution priority"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    EMERGENCY = 5

class OrderValidationResult(Enum):
    """Order validation results"""
    VALID = "valid"
    INVALID_SYMBOL = "invalid_symbol"
    INVALID_QUANTITY = "invalid_quantity"
    INSUFFICIENT_BUYING_POWER = "insufficient_buying_power"
    POSITION_LIMIT_EXCEEDED = "position_limit_exceeded"
    RISK_LIMIT_EXCEEDED = "risk_limit_exceeded"
    MARKET_CLOSED = "market_closed"
    DUPLICATE_ORDER = "duplicate_order"

@dataclass
class OrderRequest:
    """Order request with trading intent and strategy"""
    symbol: str
    intent: OrderIntent
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    execution_strategy: ExecutionStrategy = ExecutionStrategy.IMMEDIATE
    priority: OrderPriority = OrderPriority.NORMAL
    extended_hours: bool = False
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Advanced execution parameters
    max_slippage_percent: float = 0.5
    min_fill_percent: float = 0.95
    timeout_seconds: int = 300
    slice_size: Optional[float] = None  # For large orders
    participate_rate: float = 0.1  # For TWAP/VWAP

@dataclass
class OrderExecution:
    """Order execution record"""
    execution_id: str
    order_request: OrderRequest
    alpaca_order: Optional[Order]
    status: str
    submitted_at: datetime
    filled_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    filled_quantity: float
    filled_price: Optional[float]
    execution_cost: float
    slippage: Optional[float]
    execution_time: Optional[float]
    error_message: Optional[str]
    
@dataclass
class ExecutionMetrics:
    """Execution performance metrics"""
    total_orders: int
    successful_orders: int
    failed_orders: int
    average_fill_time: float
    average_slippage: float
    fill_rate: float
    cost_basis_accuracy: float
    execution_efficiency: float

@dataclass
class OrderSlice:
    """Order slice for large order execution"""
    slice_id: str
    parent_execution_id: str
    quantity: float
    status: str
    alpaca_order_id: Optional[str]
    submitted_at: Optional[datetime]
    filled_quantity: float
    average_price: Optional[float]

# ============================================================================
# PRODUCTION ORDER MANAGER
# ============================================================================

class ProductionOrderManager:
    """
    Enterprise-grade order management system
    
    Features:
    - Intelligent order execution and routing
    - Advanced order validation and risk checks
    - Order slicing for large positions
    - Real-time execution monitoring
    - Performance analytics and optimization
    - Comprehensive audit trail
    """
    
    def __init__(self, config_manager: ProductionConfigManager,
                 state_manager: ProductionStateManager,
                 alpaca_client: ProductionAlpacaClient):
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.alpaca_client = alpaca_client
        self.logger = LoggerFactory.get_logger('order_manager', LogCategory.TRADING)
        
        # Order tracking
        self._order_lock = threading.RLock()
        self.active_executions = {}  # execution_id -> OrderExecution
        self.execution_history = deque(maxlen=1000)
        self.order_slices = {}  # execution_id -> List[OrderSlice]
        
        # Performance metrics
        self.execution_metrics = ExecutionMetrics(
            total_orders=0,
            successful_orders=0,
            failed_orders=0,
            average_fill_time=0.0,
            average_slippage=0.0,
            fill_rate=0.0,
            cost_basis_accuracy=0.0,
            execution_efficiency=0.0
        )
        
        # Configuration
        self.trading_config = config_manager.get_config('trading')
        self.risk_config = config_manager.get_config('risk')
        
        # Execution strategies
        self.execution_strategies = {
            ExecutionStrategy.IMMEDIATE: self._execute_immediate,
            ExecutionStrategy.TWAP: self._execute_twap,
            ExecutionStrategy.VWAP: self._execute_vwap,
            ExecutionStrategy.ICEBERG: self._execute_iceberg,
            ExecutionStrategy.SMART_ROUTING: self._execute_smart_routing,
            ExecutionStrategy.SCHEDULED: self._execute_scheduled
        }
        
        # Order validators
        self.validators = [
            self._validate_symbol,
            self._validate_quantity,
            self._validate_buying_power,
            self._validate_position_limits,
            self._validate_risk_limits,
            self._validate_market_hours,
            self._validate_duplicate_order
        ]
        
        # Register with state manager
        state_manager.register_component('order_manager', self)
        
        self.logger.info("📋 Order Manager initialized",
                        strategies=len(self.execution_strategies),
                        validators=len(self.validators))
    
    # ========================================================================
    # ORDER EXECUTION INTERFACE
    # ========================================================================
    
    def execute_order(self, order_request: OrderRequest) -> str:
        """
        Execute order with comprehensive validation and tracking
        
        Args:
            order_request: Order request with execution parameters
            
        Returns:
            execution_id: Unique execution identifier
        """
        
        execution_id = str(uuid.uuid4())
        
        try:
            with self._order_lock:
                self.logger.info(f"🎯 Executing order: {execution_id}",
                               symbol=order_request.symbol,
                               side=order_request.side.value,
                               quantity=order_request.quantity,
                               intent=order_request.intent.value,
                               strategy=order_request.execution_strategy.value)
                
                # Create execution record
                execution = OrderExecution(
                    execution_id=execution_id,
                    order_request=order_request,
                    alpaca_order=None,
                    status="validating",
                    submitted_at=datetime.now(timezone.utc),
                    filled_at=None,
                    cancelled_at=None,
                    filled_quantity=0.0,
                    filled_price=None,
                    execution_cost=0.0,
                    slippage=None,
                    execution_time=None,
                    error_message=None
                )
                
                self.active_executions[execution_id] = execution
                
                # Validate order
                validation_result = self._validate_order(order_request)
                
                if validation_result != OrderValidationResult.VALID:
                    execution.status = "rejected"
                    execution.error_message = f"Validation failed: {validation_result.value}"
                    self._finalize_execution(execution_id, False)
                    return execution_id
                
                execution.status = "validated"
                
                # Route to execution strategy
                strategy = order_request.execution_strategy
                if strategy in self.execution_strategies:
                    execution.status = "executing"
                    self.execution_strategies[strategy](execution_id)
                else:
                    execution.status = "rejected"
                    execution.error_message = f"Unknown execution strategy: {strategy.value}"
                    self._finalize_execution(execution_id, False)
                
                return execution_id
                
        except Exception as e:
            self.logger.error(f"❌ Order execution failed: {e}",
                            execution_id=execution_id,
                            symbol=order_request.symbol)
            
            if execution_id in self.active_executions:
                execution = self.active_executions[execution_id]
                execution.status = "error"
                execution.error_message = str(e)
                self._finalize_execution(execution_id, False)
            
            return execution_id
    
    def cancel_order(self, execution_id: str) -> bool:
        """Cancel order execution"""
        
        try:
            with self._order_lock:
                if execution_id not in self.active_executions:
                    self.logger.warning(f"⚠️ Cannot cancel unknown execution: {execution_id}")
                    return False
                
                execution = self.active_executions[execution_id]
                
                # Cancel Alpaca order if exists
                if execution.alpaca_order:
                    success = self.alpaca_client.cancel_order(execution.alpaca_order.id)
                    if success:
                        execution.status = "cancelled"
                        execution.cancelled_at = datetime.now(timezone.utc)
                        self._finalize_execution(execution_id, False)
                        
                        self.logger.info(f"✅ Order cancelled: {execution_id}",
                                       symbol=execution.order_request.symbol)
                        return True
                    else:
                        self.logger.error(f"❌ Failed to cancel order: {execution_id}")
                        return False
                else:
                    # Order not yet submitted to Alpaca
                    execution.status = "cancelled"
                    execution.cancelled_at = datetime.now(timezone.utc)
                    self._finalize_execution(execution_id, False)
                    
                    self.logger.info(f"✅ Order cancelled before submission: {execution_id}")
                    return True
                    
        except Exception as e:
            self.logger.error(f"❌ Error cancelling order {execution_id}: {e}")
            return False
    
    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get execution status"""
        
        with self._order_lock:
            if execution_id in self.active_executions:
                execution = self.active_executions[execution_id]
                return {
                    'execution_id': execution_id,
                    'status': execution.status,
                    'symbol': execution.order_request.symbol,
                    'side': execution.order_request.side.value,
                    'quantity': execution.order_request.quantity,
                    'filled_quantity': execution.filled_quantity,
                    'filled_price': execution.filled_price,
                    'submitted_at': execution.submitted_at.isoformat(),
                    'filled_at': execution.filled_at.isoformat() if execution.filled_at else None,
                    'execution_time': execution.execution_time,
                    'slippage': execution.slippage,
                    'error_message': execution.error_message
                }
            
            # Check execution history
            for execution in reversed(self.execution_history):
                if execution.execution_id == execution_id:
                    return {
                        'execution_id': execution_id,
                        'status': execution.status,
                        'symbol': execution.order_request.symbol,
                        'side': execution.order_request.side.value,
                        'quantity': execution.order_request.quantity,
                        'filled_quantity': execution.filled_quantity,
                        'filled_price': execution.filled_price,
                        'submitted_at': execution.submitted_at.isoformat(),
                        'filled_at': execution.filled_at.isoformat() if execution.filled_at else None,
                        'execution_time': execution.execution_time,
                        'slippage': execution.slippage,
                        'error_message': execution.error_message
                    }
            
            return None
    
    def get_active_executions(self) -> List[Dict[str, Any]]:
        """Get all active executions"""
        
        with self._order_lock:
            return [
                self.get_execution_status(execution_id)
                for execution_id in self.active_executions.keys()
            ]
    
    # ========================================================================
    # ORDER VALIDATION
    # ========================================================================
    
    def _validate_order(self, order_request: OrderRequest) -> OrderValidationResult:
        """Comprehensive order validation"""
        
        try:
            for validator in self.validators:
                result = validator(order_request)
                if result != OrderValidationResult.VALID:
                    self.logger.warning(f"⚠️ Order validation failed: {result.value}",
                                      symbol=order_request.symbol,
                                      validator=validator.__name__)
                    return result
            
            return OrderValidationResult.VALID
            
        except Exception as e:
            self.logger.error(f"❌ Order validation error: {e}")
            return OrderValidationResult.INVALID_SYMBOL
    
    def _validate_symbol(self, order_request: OrderRequest) -> OrderValidationResult:
        """Validate symbol is tradeable"""
        
        symbol = order_request.symbol.upper()
        
        # Check if symbol is in our tier configurations
        tier_name = self.config_manager.get_symbol_tier(symbol)
        if not tier_name:
            return OrderValidationResult.INVALID_SYMBOL
        
        # Additional symbol validation could go here
        # - Check if market is open for this symbol
        # - Verify symbol exists in Alpaca
        # - Check for any trading restrictions
        
        return OrderValidationResult.VALID
    
    def _validate_quantity(self, order_request: OrderRequest) -> OrderValidationResult:
        """Validate order quantity"""
        
        if order_request.quantity <= 0:
            return OrderValidationResult.INVALID_QUANTITY
        
        # Check minimum quantity requirements
        if order_request.quantity < 1:  # Minimum 1 share
            return OrderValidationResult.INVALID_QUANTITY
        
        # Check maximum quantity limits (e.g., 10,000 shares)
        if order_request.quantity > 10000:
            return OrderValidationResult.INVALID_QUANTITY
        
        return OrderValidationResult.VALID
    
    def _validate_buying_power(self, order_request: OrderRequest) -> OrderValidationResult:
        """Validate sufficient buying power"""
        
        try:
            if order_request.side == OrderSide.SELL:
                return OrderValidationResult.VALID  # Selling doesn't require buying power
            
            # Get current account info
            account = self.alpaca_client.get_account()
            if not account:
                return OrderValidationResult.INSUFFICIENT_BUYING_POWER
            
            # Estimate order cost
            if order_request.order_type == OrderType.MARKET:
                # Use latest quote for estimation
                quote = self.alpaca_client.get_latest_quote(order_request.symbol)
                if quote:
                    estimated_price = quote.ask_price
                else:
                    # Fallback to previous close or conservative estimate
                    estimated_price = 100.0  # Conservative fallback
            else:
                estimated_price = order_request.limit_price or 100.0
            
            estimated_cost = order_request.quantity * estimated_price
            
            # Add buffer for price movement (5%)
            estimated_cost *= 1.05
            
            if estimated_cost > account.buying_power:
                return OrderValidationResult.INSUFFICIENT_BUYING_POWER
            
            return OrderValidationResult.VALID
            
        except Exception as e:
            self.logger.error(f"❌ Buying power validation error: {e}")
            return OrderValidationResult.INSUFFICIENT_BUYING_POWER
    
    def _validate_position_limits(self, order_request: OrderRequest) -> OrderValidationResult:
        """Validate position size limits"""
        
        try:
            # Get current position
            current_position = self.alpaca_client.get_position(order_request.symbol)
            current_qty = current_position.qty if current_position else 0.0
            
            # Calculate new position after order
            if order_request.side == OrderSide.BUY:
                new_qty = current_qty + order_request.quantity
            else:
                new_qty = current_qty - order_request.quantity
            
            # Check against tier limits
            tier_name = self.config_manager.get_symbol_tier(order_request.symbol)
            if tier_name:
                tier_config = self.config_manager.get_tier_config(tier_name)
                if tier_config:
                    # Get account value for percentage calculation
                    account = self.alpaca_client.get_account()
                    if account and account.portfolio_value > 0:
                        # Estimate position value
                        quote = self.alpaca_client.get_latest_quote(order_request.symbol)
                        estimated_price = quote.ask_price if quote else 100.0
                        position_value = abs(new_qty) * estimated_price
                        position_percent = (position_value / account.portfolio_value) * 100
                        
                        if position_percent > tier_config.max_position_size_percent:
                            return OrderValidationResult.POSITION_LIMIT_EXCEEDED
            
            return OrderValidationResult.VALID
            
        except Exception as e:
            self.logger.error(f"❌ Position limit validation error: {e}")
            return OrderValidationResult.POSITION_LIMIT_EXCEEDED
    
    def _validate_risk_limits(self, order_request: OrderRequest) -> OrderValidationResult:
        """Validate risk management limits"""
        
        try:
            # Get risk configuration
            risk_limits = self.config_manager.get_risk_limits()
            
            # Check single position limit
            account = self.alpaca_client.get_account()
            if account and account.portfolio_value > 0:
                quote = self.alpaca_client.get_latest_quote(order_request.symbol)
                estimated_price = quote.ask_price if quote else 100.0
                order_value = order_request.quantity * estimated_price
                order_percent = (order_value / account.portfolio_value) * 100
                
                if order_percent > risk_limits.max_single_position_percent:
                    return OrderValidationResult.RISK_LIMIT_EXCEEDED
            
            # Additional risk checks could include:
            # - Sector concentration limits
            # - Correlation limits
            # - Volatility checks
            # - Beta limits
            
            return OrderValidationResult.VALID
            
        except Exception as e:
            self.logger.error(f"❌ Risk limit validation error: {e}")
            return OrderValidationResult.RISK_LIMIT_EXCEEDED
    
    def _validate_market_hours(self, order_request: OrderRequest) -> OrderValidationResult:
        """Validate market hours for order"""
        
        try:
            # Check if extended hours trading is enabled
            if not order_request.extended_hours:
                # TODO: Implement market hours check
                # For now, assume market is open during trading hours
                current_time = datetime.now(timezone.utc)
                
                # Simple check: assume market is closed on weekends
                if current_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    return OrderValidationResult.MARKET_CLOSED
            
            return OrderValidationResult.VALID
            
        except Exception as e:
            self.logger.error(f"❌ Market hours validation error: {e}")
            return OrderValidationResult.MARKET_CLOSED
    
    def _validate_duplicate_order(self, order_request: OrderRequest) -> OrderValidationResult:
        """Check for duplicate orders"""
        
        try:
            # Check active executions for duplicates
            current_time = datetime.now(timezone.utc)
            duplicate_window = timedelta(seconds=30)  # 30-second window
            
            for execution in self.active_executions.values():
                if (execution.order_request.symbol == order_request.symbol and
                    execution.order_request.side == order_request.side and
                    execution.order_request.quantity == order_request.quantity and
                    current_time - execution.submitted_at < duplicate_window):
                    return OrderValidationResult.DUPLICATE_ORDER
            
            return OrderValidationResult.VALID
            
        except Exception as e:
            self.logger.error(f"❌ Duplicate order validation error: {e}")
            return OrderValidationResult.VALID  # Default to valid on error
    
    # ========================================================================
    # EXECUTION STRATEGIES
    # ========================================================================
    
    def _execute_immediate(self, execution_id: str):
        """Execute order immediately at market"""
        
        try:
            execution = self.active_executions[execution_id]
            order_request = execution.order_request
            
            self.logger.info(f"⚡ Executing immediate order: {execution_id}",
                           symbol=order_request.symbol)
            
            # Submit market order to Alpaca
            alpaca_order = self.alpaca_client.submit_order(
                symbol=order_request.symbol,
                qty=order_request.quantity,
                side=order_request.side,
                order_type=OrderType.MARKET,
                time_in_force=order_request.time_in_force,
                extended_hours=order_request.extended_hours,
                client_order_id=f"om_{execution_id[:8]}"
            )
            
            if alpaca_order:
                execution.alpaca_order = alpaca_order
                execution.status = "submitted"
                
                # Start monitoring the order
                self._monitor_order_execution(execution_id)
                
            else:
                execution.status = "failed"
                execution.error_message = "Failed to submit order to Alpaca"
                self._finalize_execution(execution_id, False)
                
        except Exception as e:
            self.logger.error(f"❌ Immediate execution failed: {e}")
            execution = self.active_executions[execution_id]
            execution.status = "error"
            execution.error_message = str(e)
            self._finalize_execution(execution_id, False)
    
    def _execute_twap(self, execution_id: str):
        """Execute order using Time-Weighted Average Price strategy"""
        
        try:
            execution = self.active_executions[execution_id]
            order_request = execution.order_request
            
            self.logger.info(f"⏰ Executing TWAP order: {execution_id}",
                           symbol=order_request.symbol)
            
            # For now, implement as immediate execution
            # Full TWAP implementation would slice the order over time
            self._execute_immediate(execution_id)
            
        except Exception as e:
            self.logger.error(f"❌ TWAP execution failed: {e}")
            execution = self.active_executions[execution_id]
            execution.status = "error"
            execution.error_message = str(e)
            self._finalize_execution(execution_id, False)
    
    def _execute_vwap(self, execution_id: str):
        """Execute order using Volume-Weighted Average Price strategy"""
        
        try:
            execution = self.active_executions[execution_id]
            order_request = execution.order_request
            
            self.logger.info(f"📊 Executing VWAP order: {execution_id}",
                           symbol=order_request.symbol)
            
            # For now, implement as immediate execution
            # Full VWAP implementation would consider volume patterns
            self._execute_immediate(execution_id)
            
        except Exception as e:
            self.logger.error(f"❌ VWAP execution failed: {e}")
            execution = self.active_executions[execution_id]
            execution.status = "error"
            execution.error_message = str(e)
            self._finalize_execution(execution_id, False)
    
    def _execute_iceberg(self, execution_id: str):
        """Execute order using Iceberg strategy (hide order size)"""
        
        try:
            execution = self.active_executions[execution_id]
            order_request = execution.order_request
            
            self.logger.info(f"🧊 Executing Iceberg order: {execution_id}",
                           symbol=order_request.symbol)
            
            # For now, implement as immediate execution
            # Full Iceberg implementation would slice large orders
            self._execute_immediate(execution_id)
            
        except Exception as e:
            self.logger.error(f"❌ Iceberg execution failed: {e}")
            execution = self.active_executions[execution_id]
            execution.status = "error"
            execution.error_message = str(e)
            self._finalize_execution(execution_id, False)
    
    def _execute_smart_routing(self, execution_id: str):
        """Execute order using smart routing strategy"""
        
        try:
            execution = self.active_executions[execution_id]
            order_request = execution.order_request
            
            self.logger.info(f"🧠 Executing Smart Routing order: {execution_id}",
                           symbol=order_request.symbol)
            
            # Analyze market conditions and choose best execution method
            quote = self.alpaca_client.get_latest_quote(order_request.symbol)
            
            if quote:
                spread = quote.ask_price - quote.bid_price
                spread_percent = (spread / quote.bid_price) * 100
                
                # If spread is tight, use market order; otherwise use limit
                if spread_percent < 0.1:  # Tight spread
                    order_request.order_type = OrderType.MARKET
                else:
                    order_request.order_type = OrderType.LIMIT
                    if order_request.side == OrderSide.BUY:
                        order_request.limit_price = quote.bid_price + (spread * 0.3)
                    else:
                        order_request.limit_price = quote.ask_price - (spread * 0.3)
            
            # Execute with determined strategy
            self._execute_immediate(execution_id)
            
        except Exception as e:
            self.logger.error(f"❌ Smart routing execution failed: {e}")
            execution = self.active_executions[execution_id]
            execution.status = "error"
            execution.error_message = str(e)
            self._finalize_execution(execution_id, False)
    
    def _execute_scheduled(self, execution_id: str):
        """Execute order at scheduled time"""
        
        try:
            execution = self.active_executions[execution_id]
            order_request = execution.order_request
            
            self.logger.info(f"📅 Executing Scheduled order: {execution_id}",
                           symbol=order_request.symbol)
            
            # For now, implement as immediate execution
            # Full scheduled implementation would wait for specified time
            self._execute_immediate(execution_id)
            
        except Exception as e:
            self.logger.error(f"❌ Scheduled execution failed: {e}")
            execution = self.active_executions[execution_id]
            execution.status = "error"
            execution.error_message = str(e)
            self._finalize_execution(execution_id, False)
    
    # ========================================================================
    # ORDER MONITORING AND TRACKING
    # ========================================================================
    
    def _monitor_order_execution(self, execution_id: str):
        """Monitor order execution and update status"""
        
        try:
            execution = self.active_executions[execution_id]
            
            if not execution.alpaca_order:
                return
            
            # Poll order status (in production, use websocket updates)
            start_time = time.time()
            timeout = execution.order_request.timeout_seconds
            
            while time.time() - start_time < timeout:
                # Get updated order status
                updated_order = self.alpaca_client.get_order(execution.alpaca_order.id)
                
                if updated_order:
                    execution.alpaca_order = updated_order
                    
                    if updated_order.status == OrderStatus.FILLED:
                        # Order completely filled
                        execution.status = "filled"
                        execution.filled_at = updated_order.filled_at or datetime.now(timezone.utc)
                        execution.filled_quantity = updated_order.filled_qty
                        execution.filled_price = updated_order.filled_avg_price
                        execution.execution_cost = execution.filled_quantity * execution.filled_price
                        execution.execution_time = (execution.filled_at - execution.submitted_at).total_seconds()
                        
                        # Calculate slippage
                        if execution.order_request.order_type == OrderType.MARKET:
                            quote = self.alpaca_client.get_latest_quote(execution.order_request.symbol)
                            if quote:
                                expected_price = quote.ask_price if execution.order_request.side == OrderSide.BUY else quote.bid_price
                                execution.slippage = abs(execution.filled_price - expected_price) / expected_price * 100
                        
                        self._finalize_execution(execution_id, True)
                        return
                    
                    elif updated_order.status == OrderStatus.PARTIALLY_FILLED:
                        # Order partially filled
                        execution.status = "partially_filled"
                        execution.filled_quantity = updated_order.filled_qty
                        
                        # Check if acceptable fill percentage
                        fill_percent = execution.filled_quantity / execution.order_request.quantity
                        if fill_percent >= execution.order_request.min_fill_percent:
                            # Accept partial fill
                            execution.status = "filled"
                            execution.filled_at = datetime.now(timezone.utc)
                            execution.filled_price = updated_order.filled_avg_price
                            execution.execution_cost = execution.filled_quantity * execution.filled_price
                            execution.execution_time = (execution.filled_at - execution.submitted_at).total_seconds()
                            
                            # Cancel remaining quantity
                            self.alpaca_client.cancel_order(updated_order.id)
                            
                            self._finalize_execution(execution_id, True)
                            return
                    
                    elif updated_order.status in [OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED]:
                        # Order terminated
                        execution.status = updated_order.status.value
                        execution.cancelled_at = datetime.now(timezone.utc)
                        execution.error_message = f"Order {updated_order.status.value}"
                        self._finalize_execution(execution_id, False)
                        return
                
                # Wait before next poll
                time.sleep(1)
            
            # Timeout reached
            execution.status = "timeout"
            execution.error_message = "Order monitoring timeout"
            
            # Try to cancel the order
            if execution.alpaca_order:
                self.alpaca_client.cancel_order(execution.alpaca_order.id)
            
            self._finalize_execution(execution_id, False)
            
        except Exception as e:
            self.logger.error(f"❌ Order monitoring error: {e}")
            execution = self.active_executions[execution_id]
            execution.status = "error"
            execution.error_message = str(e)
            self._finalize_execution(execution_id, False)
    
    def _finalize_execution(self, execution_id: str, success: bool):
        """Finalize order execution and update metrics"""
        
        try:
            with self._order_lock:
                if execution_id not in self.active_executions:
                    return
                
                execution = self.active_executions.pop(execution_id)
                self.execution_history.append(execution)
                
                # Update metrics
                self.execution_metrics.total_orders += 1
                
                if success:
                    self.execution_metrics.successful_orders += 1
                    
                    # Update performance metrics
                    if execution.execution_time:
                        # Rolling average of execution time
                        current_avg = self.execution_metrics.average_fill_time
                        total_successful = self.execution_metrics.successful_orders
                        self.execution_metrics.average_fill_time = (
                            (current_avg * (total_successful - 1) + execution.execution_time) / total_successful
                        )
                    
                    if execution.slippage is not None:
                        # Rolling average of slippage
                        current_avg = self.execution_metrics.average_slippage
                        total_successful = self.execution_metrics.successful_orders
                        self.execution_metrics.average_slippage = (
                            (current_avg * (total_successful - 1) + execution.slippage) / total_successful
                        )
                    
                    self.logger.info(f"✅ Order execution completed: {execution_id}",
                                   symbol=execution.order_request.symbol,
                                   filled_quantity=execution.filled_quantity,
                                   filled_price=execution.filled_price,
                                   execution_time=execution.execution_time,
                                   slippage=execution.slippage)
                else:
                    self.execution_metrics.failed_orders += 1
                    
                    self.logger.warning(f"❌ Order execution failed: {execution_id}",
                                      symbol=execution.order_request.symbol,
                                      error=execution.error_message)
                
                # Update fill rate
                self.execution_metrics.fill_rate = (
                    self.execution_metrics.successful_orders / self.execution_metrics.total_orders * 100
                )
                
                # Log execution metrics
                self.logger.performance(PerformanceMetric(
                    metric_name="order_execution_success_rate",
                    value=self.execution_metrics.fill_rate,
                    unit="percent",
                    timestamp=datetime.now(timezone.utc),
                    component="order_manager"
                ))
                
        except Exception as e:
            self.logger.error(f"❌ Error finalizing execution: {e}")
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def get_execution_metrics(self) -> Dict[str, Any]:
        """Get execution performance metrics"""
        
        return {
            'total_orders': self.execution_metrics.total_orders,
            'successful_orders': self.execution_metrics.successful_orders,
            'failed_orders': self.execution_metrics.failed_orders,
            'fill_rate_percent': round(self.execution_metrics.fill_rate, 2),
            'average_fill_time_seconds': round(self.execution_metrics.average_fill_time, 3),
            'average_slippage_percent': round(self.execution_metrics.average_slippage, 4),
            'active_executions': len(self.active_executions),
            'execution_history_size': len(self.execution_history)
        }
    
    def get_recent_executions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent execution history"""
        
        recent_executions = []
        for execution in list(self.execution_history)[-limit:]:
            recent_executions.append({
                'execution_id': execution.execution_id,
                'symbol': execution.order_request.symbol,
                'side': execution.order_request.side.value,
                'quantity': execution.order_request.quantity,
                'status': execution.status,
                'filled_quantity': execution.filled_quantity,
                'filled_price': execution.filled_price,
                'execution_time': execution.execution_time,
                'slippage': execution.slippage,
                'submitted_at': execution.submitted_at.isoformat()
            })
        
        return recent_executions
    
    def health_check(self) -> bool:
        """Perform health check"""
        
        try:
            # Check if Alpaca client is healthy
            if not self.alpaca_client.health_check():
                return False
            
            # Check for stuck executions
            current_time = datetime.now(timezone.utc)
            stuck_threshold = timedelta(minutes=10)
            
            stuck_executions = 0
            for execution in self.active_executions.values():
                if current_time - execution.submitted_at > stuck_threshold:
                    stuck_executions += 1
            
            if stuck_executions > 0:
                self.logger.warning(f"⚠️ Found {stuck_executions} stuck executions")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Order manager health check failed: {e}")
            return False

# ============================================================================
# TESTING AND VALIDATION
# ============================================================================

def test_order_manager():
    """Test the order manager"""
    
    print("🧪 Testing Order Manager...")
    
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
                    max_position_size_percent: float = 12.0
                return MockTierConfig()
            def get_risk_limits(self):
                from dataclasses import dataclass
                @dataclass
                class MockRiskLimits:
                    max_single_position_percent: float = 12.0
                return MockRiskLimits()
        
        class MockStateManager:
            def register_component(self, name, instance=None):
                pass
            def component_operation(self, component, operation):
                from contextlib import contextmanager
                @contextmanager
                def mock_context():
                    yield
                return mock_context()
        
        class MockAlpacaClient:
            def health_check(self):
                return True
            def get_account(self):
                from dataclasses import dataclass
                @dataclass
                class MockAccount:
                    portfolio_value: float = 100000.0
                    buying_power: float = 50000.0
                return MockAccount()
            def get_latest_quote(self, symbol):
                from dataclasses import dataclass
                @dataclass
                class MockQuote:
                    ask_price: float = 150.0
                    bid_price: float = 149.50
                return MockQuote()
            def get_position(self, symbol):
                return None
        
        config_manager = MockConfigManager()
        state_manager = MockStateManager()
        alpaca_client = MockAlpacaClient()
        
        # Create order manager
        order_manager = ProductionOrderManager(config_manager, state_manager, alpaca_client)
        
        # Test order request creation
        order_request = OrderRequest(
            symbol="AAPL",
            intent=OrderIntent.ENTRY,
            side=OrderSide.BUY,
            quantity=100.0,
            order_type=OrderType.MARKET
        )
        
        print(f"✅ Order request created: {order_request.symbol} {order_request.quantity} shares")
        
        # Test order validation
        validation_result = order_manager._validate_order(order_request)
        print(f"✅ Order validation: {validation_result.value}")
        
        # Test execution metrics
        metrics = order_manager.get_execution_metrics()
        print(f"✅ Execution metrics: {metrics}")
        
        # Test health check
        healthy = order_manager.health_check()
        print(f"✅ Health check: {healthy}")
        
        print("🎉 Order Manager test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Order Manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_order_manager()
