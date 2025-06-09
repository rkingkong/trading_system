#!/usr/bin/env python3
"""
🚀 PRODUCTION TRADING SYSTEM - PHASE 1: CORE INFRASTRUCTURE
Lambda Handler and Main Orchestration System

This is the central entry point and orchestration engine for the complete trading system.
Handles all Lambda requests and coordinates the entire trading operation.

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import json
import time
import os
import sys
import traceback
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import uuid
import threading
from contextlib import contextmanager
from decimal import Decimal

# ============================================================================
# CORE SYSTEM TYPES AND ENUMS
# ============================================================================

class SystemState(Enum):
    """System operational states"""
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    SHUTDOWN = "shutdown"

class ExecutionMode(Enum):
    """Execution modes for different triggers"""
    SCHEDULED_TRADING = "scheduled_trading"
    MANUAL_TRIGGER = "manual_trigger"
    EMERGENCY_MODE = "emergency_mode"
    HEALTH_CHECK = "health_check"
    PERFORMANCE_ANALYSIS = "performance_analysis"

class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

@dataclass
class ExecutionContext:
    """Execution context for tracking performance and constraints"""
    execution_id: str
    start_time: float
    max_execution_time: int
    mode: ExecutionMode
    timeout_buffer: int = 30
    
    def time_remaining(self) -> float:
        """Get remaining execution time in seconds"""
        elapsed = time.time() - self.start_time
        return max(0, self.max_execution_time - elapsed - self.timeout_buffer)
    
    def elapsed_time(self) -> float:
        """Get elapsed execution time in seconds"""
        return time.time() - self.start_time
    
    def is_timeout_approaching(self, buffer_seconds: int = 60) -> bool:
        """Check if timeout is approaching"""
        return self.time_remaining() < buffer_seconds

@dataclass
class SystemHealth:
    """System health status"""
    state: SystemState
    timestamp: datetime
    components_status: Dict[str, bool]
    performance_metrics: Dict[str, float]
    error_count: int
    last_successful_execution: Optional[datetime]
    uptime_seconds: float

@dataclass
class ExecutionResult:
    """Result of a trading system execution"""
    execution_id: str
    status: str
    timestamp: datetime
    execution_time: float
    mode: ExecutionMode
    components_executed: List[str]
    trades_executed: int
    alerts_generated: int
    performance_metrics: Dict[str, Any]
    errors: List[str]
    warnings: List[str]

# ============================================================================
# PRODUCTION LOGGING SYSTEM
# ============================================================================

class ProductionLogger:
    """
    Production-grade structured logging system with CloudWatch integration
    """
    
    def __init__(self, component_name: str):
        self.component_name = component_name
        self.logger = logging.getLogger(f"trading_system.{component_name}")
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup structured logging with appropriate handlers"""
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # Set log level from environment
        log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
        self.logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # Create console handler for Lambda
        console_handler = logging.StreamHandler(sys.stdout)
        
        # Create structured formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(console_handler)
        
        # Prevent duplicate logs
        self.logger.propagate = False
    
    def info(self, message: str, **kwargs):
        """Log info message with structured data"""
        self._log_with_context('info', message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message with structured data"""
        self._log_with_context('warning', message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message with structured data"""
        self._log_with_context('error', message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log critical message with structured data"""
        self._log_with_context('critical', message, **kwargs)
    
    def _log_with_context(self, level: str, message: str, **kwargs):
        """Log with additional context data"""
        
        # Add execution context
        context_data = {
            'component': self.component_name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'environment': os.environ.get('ENVIRONMENT', 'unknown')
        }
        
        # Add any additional context
        if kwargs:
            context_data.update(kwargs)
        
        # Format message with context
        if context_data:
            formatted_message = f"{message} | Context: {json.dumps(context_data, default=str)}"
        else:
            formatted_message = message
        
        # Log at appropriate level
        log_method = getattr(self.logger, level)
        log_method(formatted_message)

# ============================================================================
# CONFIGURATION MANAGEMENT SYSTEM
# ============================================================================

class ConfigurationManager:
    """
    Production-grade configuration management with environment validation
    """
    
    def __init__(self):
        self.logger = ProductionLogger('config_manager')
        self.config = {}
        self.required_env_vars = {
            'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPACA_BASE_URL',
            'ENVIRONMENT', 'TRADING_ENABLED', 'NOTIFICATION_EMAIL'
        }
        self._load_configuration()
    
    def _load_configuration(self):
        """Load and validate all configuration from environment variables"""
        
        try:
            self.logger.info("🔧 Loading production configuration...")
            
            # Validate required environment variables
            missing_vars = []
            for var in self.required_env_vars:
                if not os.environ.get(var):
                    missing_vars.append(var)
            
            if missing_vars:
                raise ValueError(f"Missing required environment variables: {missing_vars}")
            
            # Load trading configuration
            self.config['trading'] = {
                'enabled': os.environ.get('TRADING_ENABLED', 'false').lower() == 'true',
                'environment': os.environ.get('ENVIRONMENT', 'production'),
                'extended_hours': os.environ.get('EXTENDED_HOURS', 'false').lower() == 'true',
                'paper_trading': True,  # Always paper trading for safety
                'max_concurrent_trades': int(os.environ.get('MAX_CONCURRENT_TRADES', '5')),
                'max_position_size_percent': float(os.environ.get('MAX_POSITION_SIZE', '0.12')),
                'min_confidence_threshold': float(os.environ.get('MIN_CONFIDENCE', '70.0'))
            }
            
            # Load Alpaca configuration
            self.config['alpaca'] = {
                'api_key': os.environ.get('ALPACA_API_KEY'),
                'secret_key': os.environ.get('ALPACA_SECRET_KEY'), 
                'base_url': os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets'),
                'timeout': int(os.environ.get('ALPACA_TIMEOUT', '30')),
                'max_retries': int(os.environ.get('ALPACA_MAX_RETRIES', '3'))
            }
            
            # Load market data APIs
            self.config['market_data'] = {
                'alpha_vantage_key': os.environ.get('ALPHA_VANTAGE_KEY'),
                'newsapi_key': os.environ.get('NEWSAPI_KEY'),
                'cache_ttl': int(os.environ.get('CACHE_TTL', '300'))
            }
            
            # Load AWS configuration
            self.config['aws'] = {
                'region': os.environ.get('AWS_REGION', 'us-east-1'),
                'sns_topic_arn': os.environ.get('SNS_TOPIC_ARN'),
                'signals_table': os.environ.get('SIGNALS_TABLE'),
                'performance_table': os.environ.get('PERFORMANCE_TABLE'),
                'portfolio_table': os.environ.get('PORTFOLIO_TABLE')
            }
            
            # Load system configuration
            self.config['system'] = {
                'log_level': os.environ.get('LOG_LEVEL', 'INFO'),
                'notification_email': os.environ.get('NOTIFICATION_EMAIL'),
                'max_execution_time': int(os.environ.get('LAMBDA_TIMEOUT', '270')),
                'timeout_buffer': 30,
                'health_check_interval': 300
            }
            
            # Load AI configuration
            self.config['ai'] = {
                'enabled': True,
                'confidence_threshold': 70.0,
                'technical_weight': 0.35,
                'fundamental_weight': 0.25,
                'sentiment_weight': 0.20,
                'risk_weight': 0.15,
                'portfolio_weight': 0.05
            }
            
            # Load risk management configuration
            self.config['risk'] = {
                'max_portfolio_loss_percent': 5.0,
                'max_drawdown_percent': 15.0,
                'max_single_position_percent': 12.0,
                'max_sector_concentration_percent': 30.0,
                'min_cash_percent': 3.0,
                'max_tier3_allocation_percent': 15.0
            }
            
            self.logger.info("✅ Configuration loaded successfully", 
                           trading_enabled=self.config['trading']['enabled'],
                           environment=self.config['trading']['environment'])
            
        except Exception as e:
            self.logger.critical(f"❌ Configuration loading failed: {e}")
            raise
    
    def get(self, section: str, key: str = None, default=None):
        """Get configuration value"""
        if key is None:
            return self.config.get(section, default)
        return self.config.get(section, {}).get(key, default)
    
    def validate_trading_enabled(self) -> bool:
        """Validate that trading is enabled and safe to proceed"""
        if not self.config['trading']['enabled']:
            self.logger.warning("⚠️ Trading is disabled in configuration")
            return False
        
        if self.config['trading']['environment'] not in ['production', 'staging']:
            self.logger.warning(f"⚠️ Non-production environment: {self.config['trading']['environment']}")
        
        return True

# ============================================================================
# GLOBAL STATE MANAGEMENT
# ============================================================================

class GlobalStateManager:
    """
    Thread-safe global state management for the trading system
    """
    
    def __init__(self):
        self.logger = ProductionLogger('state_manager')
        self._lock = threading.RLock()
        
        # System state
        self.system_state = SystemState.INITIALIZING
        self.startup_time = datetime.now(timezone.utc)
        
        # Component health tracking
        self.component_health = {
            'config_manager': False,
            'alpaca_client': False,
            'ai_engine': False,
            'risk_manager': False,
            'email_notifier': False,
            'database_manager': False
        }
        
        # Performance metrics
        self.performance_metrics = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'avg_execution_time': 0.0,
            'total_trades': 0,
            'successful_trades': 0,
            'total_alerts': 0
        }
        
        # Error tracking
        self.error_count = 0
        self.last_error = None
        self.last_successful_execution = None
        
        # Trading state
        self.trading_enabled = False
        self.emergency_stop = False
        self.current_execution_id = None
        
        # Component instances (will be set by orchestrator)
        self.components = {}
    
    @contextmanager
    def execution_context(self, execution_id: str, mode: ExecutionMode):
        """Context manager for tracking execution state"""
        with self._lock:
            self.current_execution_id = execution_id
            self.performance_metrics['total_executions'] += 1
        
        try:
            yield
            with self._lock:
                self.performance_metrics['successful_executions'] += 1
                self.last_successful_execution = datetime.now(timezone.utc)
        except Exception as e:
            with self._lock:
                self.performance_metrics['failed_executions'] += 1
                self.error_count += 1
                self.last_error = str(e)
            raise
        finally:
            with self._lock:
                self.current_execution_id = None
    
    def update_component_health(self, component: str, healthy: bool):
        """Update component health status"""
        with self._lock:
            self.component_health[component] = healthy
            self._update_system_state()
    
    def update_performance_metric(self, metric: str, value: Union[int, float]):
        """Update performance metric"""
        with self._lock:
            if metric in self.performance_metrics:
                if metric.startswith('avg_'):
                    # Calculate rolling average
                    current_avg = self.performance_metrics[metric]
                    total_count = self.performance_metrics['total_executions']
                    self.performance_metrics[metric] = ((current_avg * (total_count - 1)) + value) / total_count
                else:
                    self.performance_metrics[metric] = value
    
    def _update_system_state(self):
        """Update overall system state based on component health"""
        healthy_components = sum(self.component_health.values())
        total_components = len(self.component_health)
        
        if self.emergency_stop:
            self.system_state = SystemState.ERROR
        elif healthy_components == total_components:
            self.system_state = SystemState.HEALTHY
        elif healthy_components >= total_components * 0.7:
            self.system_state = SystemState.DEGRADED
        else:
            self.system_state = SystemState.ERROR
    
    def get_system_health(self) -> SystemHealth:
        """Get current system health status"""
        with self._lock:
            uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
            
            return SystemHealth(
                state=self.system_state,
                timestamp=datetime.now(timezone.utc),
                components_status=self.component_health.copy(),
                performance_metrics=self.performance_metrics.copy(),
                error_count=self.error_count,
                last_successful_execution=self.last_successful_execution,
                uptime_seconds=uptime
            )
    
    def set_emergency_stop(self, reason: str):
        """Activate emergency stop"""
        with self._lock:
            self.emergency_stop = True
            self.trading_enabled = False
            self.system_state = SystemState.ERROR
            self.logger.critical(f"🚨 EMERGENCY STOP ACTIVATED: {reason}")

# ============================================================================
# MAIN ORCHESTRATION ENGINE
# ============================================================================

class TradingSystemOrchestrator:
    """
    Main orchestration engine for the complete trading system
    Coordinates all components and manages execution flow
    """
    
    def __init__(self):
        self.logger = ProductionLogger('orchestrator')
        self.config_manager = ConfigurationManager()
        self.state_manager = GlobalStateManager()
        
        # Component initialization will happen in initialize_components()
        self.components_initialized = False
        
        self.logger.info("🚀 Trading System Orchestrator initialized")
    
    def initialize_components(self):
        """Initialize all system components"""
        try:
            self.logger.info("🔧 Initializing system components...")
            
            # Update component health as we initialize
            self.state_manager.update_component_health('config_manager', True)
            
            # TODO: Initialize other components in subsequent phases
            # self._initialize_alpaca_client()
            # self._initialize_ai_engine()
            # self._initialize_risk_manager()
            # self._initialize_email_notifier()
            # self._initialize_database_manager()
            
            self.components_initialized = True
            self.state_manager.trading_enabled = self.config_manager.validate_trading_enabled()
            
            self.logger.info("✅ Component initialization complete",
                           trading_enabled=self.state_manager.trading_enabled)
            
        except Exception as e:
            self.logger.critical(f"❌ Component initialization failed: {e}")
            self.state_manager.set_emergency_stop(f"Component initialization failed: {e}")
            raise
    
    def execute_trading_cycle(self, context: ExecutionContext) -> ExecutionResult:
        """
        Execute a complete trading cycle
        
        Args:
            context: Execution context with timing and mode information
            
        Returns:
            ExecutionResult with comprehensive execution details
        """
        
        self.logger.info(f"🎯 Starting trading cycle: {context.execution_id}",
                        mode=context.mode.value,
                        max_time=context.max_execution_time)
        
        result = ExecutionResult(
            execution_id=context.execution_id,
            status="running",
            timestamp=datetime.now(timezone.utc),
            execution_time=0.0,
            mode=context.mode,
            components_executed=[],
            trades_executed=0,
            alerts_generated=0,
            performance_metrics={},
            errors=[],
            warnings=[]
        )
        
        try:
            with self.state_manager.execution_context(context.execution_id, context.mode):
                
                # Phase 1: System Health Check
                self._execute_health_check(context, result)
                
                # Phase 2: Market Analysis (Future implementation)
                if context.time_remaining() > 60:
                    self._execute_market_analysis(context, result)
                
                # Phase 3: Trading Execution (Future implementation)
                if context.time_remaining() > 30 and self.state_manager.trading_enabled:
                    self._execute_trading_operations(context, result)
                
                # Phase 4: Performance Analysis (Future implementation)
                if context.time_remaining() > 15:
                    self._execute_performance_analysis(context, result)
                
                # Phase 5: Notifications (Future implementation)
                if context.time_remaining() > 5:
                    self._execute_notifications(context, result)
                
                # Finalize execution
                result.status = "completed"
                result.execution_time = context.elapsed_time()
                
                self.state_manager.update_performance_metric('avg_execution_time', result.execution_time)
                
                self.logger.info(f"✅ Trading cycle completed: {context.execution_id}",
                               execution_time=result.execution_time,
                               components_executed=len(result.components_executed))
                
        except Exception as e:
            result.status = "failed"
            result.execution_time = context.elapsed_time()
            result.errors.append(str(e))
            
            self.logger.error(f"❌ Trading cycle failed: {context.execution_id}",
                            error=str(e),
                            execution_time=result.execution_time)
            raise
        
        return result
    
    def _execute_health_check(self, context: ExecutionContext, result: ExecutionResult):
        """Execute system health check phase"""
        
        self.logger.info("🏥 Executing health check phase")
        
        try:
            # Check system health
            health = self.state_manager.get_system_health()
            
            # Validate configuration
            config_valid = self.config_manager.validate_trading_enabled()
            
            # Check component status
            unhealthy_components = [
                component for component, healthy in health.components_status.items()
                if not healthy
            ]
            
            if unhealthy_components:
                warning_msg = f"Unhealthy components detected: {unhealthy_components}"
                result.warnings.append(warning_msg)
                self.logger.warning(warning_msg)
            
            # Update result
            result.components_executed.append("health_check")
            result.performance_metrics['system_health_score'] = (
                sum(health.components_status.values()) / len(health.components_status) * 100
            )
            
            self.logger.info("✅ Health check completed",
                           system_state=health.state.value,
                           healthy_components=sum(health.components_status.values()),
                           total_components=len(health.components_status))
            
        except Exception as e:
            error_msg = f"Health check failed: {e}"
            result.errors.append(error_msg)
            self.logger.error(error_msg)
            raise
    
    def _execute_market_analysis(self, context: ExecutionContext, result: ExecutionResult):
        """Execute market analysis phase (placeholder for future implementation)"""
        
        self.logger.info("📊 Executing market analysis phase")
        
        try:
            # TODO: Implement market analysis in Phase 3
            # - Fetch market data
            # - Run technical analysis
            # - Perform sentiment analysis
            # - Generate trading signals
            
            result.components_executed.append("market_analysis")
            
            self.logger.info("✅ Market analysis completed (placeholder)")
            
        except Exception as e:
            error_msg = f"Market analysis failed: {e}"
            result.errors.append(error_msg)
            self.logger.error(error_msg)
            raise
    
    def _execute_trading_operations(self, context: ExecutionContext, result: ExecutionResult):
        """Execute trading operations phase (placeholder for future implementation)"""
        
        self.logger.info("⚡ Executing trading operations phase")
        
        try:
            # TODO: Implement trading operations in Phase 2
            # - Execute trades based on signals
            # - Update positions
            # - Apply risk management
            # - Track performance
            
            result.components_executed.append("trading_operations")
            
            self.logger.info("✅ Trading operations completed (placeholder)")
            
        except Exception as e:
            error_msg = f"Trading operations failed: {e}"
            result.errors.append(error_msg)
            self.logger.error(error_msg)
            raise
    
    def _execute_performance_analysis(self, context: ExecutionContext, result: ExecutionResult):
        """Execute performance analysis phase (placeholder for future implementation)"""
        
        self.logger.info("📈 Executing performance analysis phase")
        
        try:
            # TODO: Implement performance analysis in Phase 3
            # - Calculate portfolio performance
            # - Generate analytics
            # - Update metrics
            
            result.components_executed.append("performance_analysis")
            
            self.logger.info("✅ Performance analysis completed (placeholder)")
            
        except Exception as e:
            error_msg = f"Performance analysis failed: {e}"
            result.errors.append(error_msg)
            self.logger.error(error_msg)
            raise
    
    def _execute_notifications(self, context: ExecutionContext, result: ExecutionResult):
        """Execute notifications phase (placeholder for future implementation)"""
        
        self.logger.info("📧 Executing notifications phase")
        
        try:
            # TODO: Implement notifications in Phase 4
            # - Send email notifications
            # - Generate alerts
            # - Update dashboards
            
            result.components_executed.append("notifications")
            
            self.logger.info("✅ Notifications completed (placeholder)")
            
        except Exception as e:
            error_msg = f"Notifications failed: {e}"
            result.errors.append(error_msg)
            self.logger.error(error_msg)
            raise
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        
        health = self.state_manager.get_system_health()
        config = self.config_manager.get('trading')
        
        return {
            'system_state': health.state.value,
            'timestamp': health.timestamp.isoformat(),
            'uptime_seconds': health.uptime_seconds,
            'components_status': health.components_status,
            'performance_metrics': health.performance_metrics,
            'trading_enabled': self.state_manager.trading_enabled,
            'emergency_stop': self.state_manager.emergency_stop,
            'configuration': {
                'environment': config['environment'],
                'paper_trading': config.get('paper_trading', True),
                'max_position_size': config['max_position_size_percent']
            },
            'error_count': health.error_count,
            'last_successful_execution': (
                health.last_successful_execution.isoformat()
                if health.last_successful_execution else None
            )
        }

# ============================================================================
# LAMBDA HANDLER - MAIN ENTRY POINT
# ============================================================================

# Global orchestrator instance (Lambda container reuse)
orchestrator: Optional[TradingSystemOrchestrator] = None

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Main Lambda handler - Entry point for all trading system requests
    
    Args:
        event: Lambda event data
        context: Lambda context object
        
    Returns:
        Formatted response with execution results
    """
    
    # Create execution context
    execution_id = str(uuid.uuid4())
    max_time = getattr(context, 'remaining_time_in_millis', lambda: 270000)() // 1000
    
    # Determine execution mode from event
    execution_mode = _determine_execution_mode(event)
    
    exec_context = ExecutionContext(
        execution_id=execution_id,
        start_time=time.time(),
        max_execution_time=max_time,
        mode=execution_mode
    )
    
    # Initialize logger for this execution
    logger = ProductionLogger('lambda_handler')
    
    logger.info(f"🚀 Lambda execution started: {execution_id}",
               execution_mode=execution_mode.value,
               max_time=max_time,
               event_source=event.get('source', 'unknown'))
    
    try:
        # Initialize or reuse orchestrator
        global orchestrator
        if orchestrator is None:
            logger.info("🔧 Initializing new orchestrator instance")
            orchestrator = TradingSystemOrchestrator()
            orchestrator.initialize_components()
        
        # Handle different execution modes
        if execution_mode == ExecutionMode.HEALTH_CHECK:
            result = _handle_health_check(orchestrator, exec_context, logger)
        else:
            # Execute full trading cycle
            execution_result = orchestrator.execute_trading_cycle(exec_context)
            result = _format_execution_response(execution_result, exec_context)
        
        logger.info(f"✅ Lambda execution completed: {execution_id}",
                   execution_time=exec_context.elapsed_time(),
                   status=result.get('status', 'unknown'))
        
        return result
        
    except Exception as e:
        # Handle critical errors
        error_msg = f"Critical Lambda execution error: {str(e)}"
        logger.critical(error_msg, 
                       execution_id=execution_id,
                       execution_time=exec_context.elapsed_time(),
                       traceback=traceback.format_exc())
        
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'status': 'error',
                'execution_id': execution_id,
                'error': error_msg,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'execution_time': exec_context.elapsed_time()
            }, default=str)
        }

def _determine_execution_mode(event: Dict[str, Any]) -> ExecutionMode:
    """Determine execution mode based on event data"""
    
    # Check event source
    source = event.get('source', '')
    
    if source == 'aws.events':
        # Scheduled execution
        return ExecutionMode.SCHEDULED_TRADING
    elif 'health' in event.get('path', '').lower():
        # Health check request
        return ExecutionMode.HEALTH_CHECK
    elif event.get('manual_trigger'):
        # Manual trigger
        return ExecutionMode.MANUAL_TRIGGER
    elif event.get('emergency'):
        # Emergency mode
        return ExecutionMode.EMERGENCY_MODE
    else:
        # Default to scheduled trading
        return ExecutionMode.SCHEDULED_TRADING

def _handle_health_check(orchestrator: TradingSystemOrchestrator, 
                        context: ExecutionContext,
                        logger: ProductionLogger) -> Dict[str, Any]:
    """Handle health check requests"""
    
    logger.info("🏥 Processing health check request")
    
    try:
        status = orchestrator.get_system_status()
        
        # Determine HTTP status code
        if status['system_state'] == 'healthy':
            status_code = 200
        elif status['system_state'] == 'degraded':
            status_code = 206  # Partial Content
        else:
            status_code = 503  # Service Unavailable
        
        return {
            'statusCode': status_code,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'status': 'health_check_completed',
                'execution_id': context.execution_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'execution_time': context.elapsed_time(),
                'system_status': status
            }, default=str)
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'status': 'health_check_failed',
                'execution_id': context.execution_id,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, default=str)
        }

def _format_execution_response(execution_result: ExecutionResult, 
                             context: ExecutionContext) -> Dict[str, Any]:
    """Format execution result as Lambda response"""
    
    # Determine status code
    if execution_result.status == 'completed':
        status_code = 200
    elif execution_result.status == 'failed':
        status_code = 500
    else:
        status_code = 202  # Accepted (still processing)
    
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({
            'status': execution_result.status,
            'execution_id': execution_result.execution_id,
            'timestamp': execution_result.timestamp.isoformat(),
            'execution_time': execution_result.execution_time,
            'mode': execution_result.mode.value,
            'summary': {
                'components_executed': len(execution_result.components_executed),
                'trades_executed': execution_result.trades_executed,
                'alerts_generated': execution_result.alerts_generated,
                'errors': len(execution_result.errors),
                'warnings': len(execution_result.warnings)
            },
            'performance_metrics': execution_result.performance_metrics,
            'components_executed': execution_result.components_executed,
            'errors': execution_result.errors,
            'warnings': execution_result.warnings
        }, default=str)
    }

# ============================================================================
# DEVELOPMENT AND TESTING UTILITIES
# ============================================================================

def test_lambda_handler():
    """Test the lambda handler locally"""
    
    print("🧪 Testing Lambda Handler...")
    
    # Mock Lambda context
    class MockContext:
        def remaining_time_in_millis(self):
            return 270000  # 4.5 minutes
    
    # Test health check
    health_event = {
        'source': 'manual',
        'path': '/health',
        'health': True
    }
    
    result = lambda_handler(health_event, MockContext())
    print(f"Health Check Result: {result['statusCode']}")
    
    # Test trading cycle
    trading_event = {
        'source': 'aws.events',
        'detail-type': 'Scheduled Event'
    }
    
    result = lambda_handler(trading_event, MockContext())
    print(f"Trading Cycle Result: {result['statusCode']}")
    
    print("✅ Lambda handler test completed")

if __name__ == "__main__":
    # Run tests if executed directly
    test_lambda_handler()
