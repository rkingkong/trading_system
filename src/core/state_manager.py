#!/usr/bin/env python3
"""
🏛️ PRODUCTION TRADING SYSTEM - GLOBAL STATE MANAGEMENT SYSTEM
src/core/state_manager.py

Enterprise-grade thread-safe state management for the complete trading system.
Manages component health, performance metrics, trading state, error tracking,
and provides a unified interface for all system state operations.

Features:
- Thread-safe state operations with comprehensive locking
- Component health monitoring and lifecycle management
- Performance metrics collection and aggregation
- Trading state management with safety controls
- Error tracking and recovery coordination
- Audit trail and compliance logging
- Real-time state synchronization
- Emergency stop and circuit breaker functionality

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
from contextlib import contextmanager
from collections import defaultdict, deque
import json
import statistics

# Import our other core components
try:
    from .logger import LoggerFactory, LogCategory, PerformanceMetric, SecurityEvent
    from .config_manager import ProductionConfigManager, RiskLimits
except ImportError:
    # Fallback for testing
    from logger import LoggerFactory, LogCategory, PerformanceMetric, SecurityEvent
    from config_manager import ProductionConfigManager, RiskLimits

# ============================================================================
# STATE MANAGEMENT ENUMS AND TYPES
# ============================================================================

class SystemState(Enum):
    """Overall system operational states"""
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    SHUTDOWN = "shutdown"
    EMERGENCY = "emergency"

class ComponentState(Enum):
    """Individual component states"""
    UNKNOWN = "unknown"
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISABLED = "disabled"
    MAINTENANCE = "maintenance"

class TradingState(Enum):
    """Trading system operational states"""
    DISABLED = "disabled"
    ENABLED = "enabled"
    PAUSED = "paused"
    EMERGENCY_STOP = "emergency_stop"
    MAINTENANCE = "maintenance"

class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

@dataclass
class ComponentHealth:
    """Health status for a system component"""
    name: str
    state: ComponentState
    last_heartbeat: datetime
    error_count: int
    last_error: Optional[str]
    performance_score: float  # 0-100
    uptime_seconds: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PerformanceSnapshot:
    """Performance metrics snapshot"""
    timestamp: datetime
    execution_time: float
    memory_usage: Optional[float]
    api_calls: int
    errors: int
    trades_executed: int
    success_rate: float
    custom_metrics: Dict[str, float] = field(default_factory=dict)

@dataclass
class TradingSession:
    """Trading session information"""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime]
    execution_mode: str
    trades_executed: int
    total_pnl: float
    max_drawdown: float
    active_positions: int
    errors: List[str] = field(default_factory=list)

@dataclass
class SystemAlert:
    """System alert information"""
    alert_id: str
    severity: AlertSeverity
    component: str
    message: str
    timestamp: datetime
    resolved: bool = False
    resolution_time: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

# ============================================================================
# THREAD-SAFE STATE CONTAINERS
# ============================================================================

class ThreadSafeCounter:
    """Thread-safe counter for metrics"""
    
    def __init__(self, initial_value: int = 0):
        self._value = initial_value
        self._lock = threading.RLock()
    
    def increment(self, amount: int = 1) -> int:
        """Increment counter and return new value"""
        with self._lock:
            self._value += amount
            return self._value
    
    def decrement(self, amount: int = 1) -> int:
        """Decrement counter and return new value"""
        with self._lock:
            self._value -= amount
            return self._value
    
    def set(self, value: int) -> int:
        """Set counter value"""
        with self._lock:
            self._value = value
            return self._value
    
    def get(self) -> int:
        """Get current value"""
        with self._lock:
            return self._value
    
    def reset(self) -> int:
        """Reset counter to zero"""
        with self._lock:
            old_value = self._value
            self._value = 0
            return old_value

class ThreadSafeMetrics:
    """Thread-safe metrics collection"""
    
    def __init__(self, max_history: int = 1000):
        self._metrics = defaultdict(deque)
        self._max_history = max_history
        self._lock = threading.RLock()
    
    def add_metric(self, name: str, value: float, timestamp: datetime = None):
        """Add metric value"""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        with self._lock:
            metric_deque = self._metrics[name]
            metric_deque.append((timestamp, value))
            
            # Maintain max history size
            while len(metric_deque) > self._max_history:
                metric_deque.popleft()
    
    def get_metric_stats(self, name: str, window_seconds: int = None) -> Dict[str, float]:
        """Get statistics for a metric"""
        with self._lock:
            if name not in self._metrics:
                return {}
            
            values = list(self._metrics[name])
            if not values:
                return {}
            
            # Filter by time window if specified
            if window_seconds:
                cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
                values = [(ts, val) for ts, val in values if ts >= cutoff_time]
            
            if not values:
                return {}
            
            metric_values = [val for _, val in values]
            
            return {
                'count': len(metric_values),
                'average': statistics.mean(metric_values),
                'min': min(metric_values),
                'max': max(metric_values),
                'latest': metric_values[-1],
                'median': statistics.median(metric_values),
                'stddev': statistics.stdev(metric_values) if len(metric_values) > 1 else 0
            }
    
    def get_all_metrics(self) -> Dict[str, Dict[str, float]]:
        """Get all metric statistics"""
        with self._lock:
            return {name: self.get_metric_stats(name) for name in self._metrics.keys()}

# ============================================================================
# PRODUCTION STATE MANAGER
# ============================================================================

class ProductionStateManager:
    """
    Enterprise-grade global state management system
    
    Manages:
    - System and component health monitoring
    - Performance metrics collection and analysis
    - Trading state and session management
    - Error tracking and recovery coordination
    - Alert management and notification
    - Audit trail and compliance logging
    """
    
    def __init__(self, config_manager: ProductionConfigManager):
        self.config_manager = config_manager
        self.logger = LoggerFactory.get_logger('state_manager', LogCategory.SYSTEM)
        
        # Core state management
        self._master_lock = threading.RLock()
        self.system_start_time = datetime.now(timezone.utc)
        self.instance_id = str(uuid.uuid4())
        
        # System state
        self.system_state = SystemState.INITIALIZING
        self.trading_state = TradingState.DISABLED
        self.emergency_stop_active = False
        self.maintenance_mode = False
        
        # Component health tracking
        self.component_health = {}
        self.component_registry = set()
        
        # Performance metrics
        self.performance_metrics = ThreadSafeMetrics(max_history=10000)
        self.execution_counters = {
            'total_executions': ThreadSafeCounter(),
            'successful_executions': ThreadSafeCounter(),
            'failed_executions': ThreadSafeCounter(),
            'api_calls': ThreadSafeCounter(),
            'trades_executed': ThreadSafeCounter(),
            'alerts_generated': ThreadSafeCounter()
        }
        
        # Trading session management
        self.current_session: Optional[TradingSession] = None
        self.session_history = deque(maxlen=100)
        
        # Error tracking
        self.error_history = deque(maxlen=500)
        self.component_errors = defaultdict(list)
        
        # Alert management
        self.active_alerts = {}
        self.alert_history = deque(maxlen=1000)
        
        # Execution context tracking
        self.active_executions = {}
        self.execution_history = deque(maxlen=200)
        
        # Risk state
        self.risk_limits = config_manager.get_risk_limits()
        self.risk_violations = defaultdict(list)
        
        # Component instances (will be populated by orchestrator)
        self.component_instances = {}
        
        self.logger.info("🏛️ Production State Manager initialized",
                        instance_id=self.instance_id)
    
    # ========================================================================
    # SYSTEM STATE MANAGEMENT
    # ========================================================================
    
    def get_system_state(self) -> SystemState:
        """Get current system state"""
        with self._master_lock:
            return self.system_state
    
    def set_system_state(self, new_state: SystemState, reason: str = None):
        """Set system state with logging"""
        with self._master_lock:
            old_state = self.system_state
            self.system_state = new_state
            
            self.logger.info(f"🔄 System state changed: {old_state.value} → {new_state.value}",
                           reason=reason or "No reason provided")
            
            # Log audit event
            self.logger.audit("system_state_change", {
                'old_state': old_state.value,
                'new_state': new_state.value,
                'reason': reason,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
    
    def get_trading_state(self) -> TradingState:
        """Get current trading state"""
        with self._master_lock:
            return self.trading_state
    
    def set_trading_state(self, new_state: TradingState, reason: str = None):
        """Set trading state with validation"""
        with self._master_lock:
            old_state = self.trading_state
            
            # Validate state transition
            if not self._is_valid_trading_state_transition(old_state, new_state):
                raise StateTransitionError(
                    f"Invalid trading state transition: {old_state.value} → {new_state.value}"
                )
            
            self.trading_state = new_state
            
            self.logger.info(f"💰 Trading state changed: {old_state.value} → {new_state.value}",
                           reason=reason or "No reason provided")
            
            # Special handling for emergency stop
            if new_state == TradingState.EMERGENCY_STOP:
                self.emergency_stop_active = True
                self._handle_emergency_stop(reason)
    
    def _is_valid_trading_state_transition(self, from_state: TradingState, 
                                         to_state: TradingState) -> bool:
        """Validate trading state transitions"""
        
        # Emergency stop can be activated from any state
        if to_state == TradingState.EMERGENCY_STOP:
            return True
        
        # From emergency stop, can only go to disabled or maintenance
        if from_state == TradingState.EMERGENCY_STOP:
            return to_state in [TradingState.DISABLED, TradingState.MAINTENANCE]
        
        # Normal transitions
        valid_transitions = {
            TradingState.DISABLED: [TradingState.ENABLED, TradingState.MAINTENANCE],
            TradingState.ENABLED: [TradingState.PAUSED, TradingState.DISABLED, TradingState.MAINTENANCE],
            TradingState.PAUSED: [TradingState.ENABLED, TradingState.DISABLED],
            TradingState.MAINTENANCE: [TradingState.DISABLED]
        }
        
        return to_state in valid_transitions.get(from_state, [])
    
    def activate_emergency_stop(self, reason: str):
        """Activate emergency stop"""
        self.set_trading_state(TradingState.EMERGENCY_STOP, reason)
    
    def _handle_emergency_stop(self, reason: str):
        """Handle emergency stop activation"""
        
        # Generate critical alert
        alert = SystemAlert(
            alert_id=str(uuid.uuid4()),
            severity=AlertSeverity.EMERGENCY,
            component="state_manager",
            message=f"Emergency stop activated: {reason}",
            timestamp=datetime.now(timezone.utc)
        )
        self.add_alert(alert)
        
        # Log security event
        security_event = SecurityEvent(
            event_type="emergency_stop",
            severity="critical",
            source="state_manager",
            description=f"Emergency stop activated: {reason}",
            timestamp=datetime.now(timezone.utc),
            context={'reason': reason, 'trading_state': self.trading_state.value}
        )
        self.logger.security(security_event)
    
    # ========================================================================
    # COMPONENT HEALTH MANAGEMENT
    # ========================================================================
    
    def register_component(self, component_name: str, instance: Any = None):
        """Register a system component"""
        with self._master_lock:
            self.component_registry.add(component_name)
            
            if instance is not None:
                self.component_instances[component_name] = instance
            
            # Initialize health tracking
            self.component_health[component_name] = ComponentHealth(
                name=component_name,
                state=ComponentState.INITIALIZING,
                last_heartbeat=datetime.now(timezone.utc),
                error_count=0,
                last_error=None,
                performance_score=100.0,
                uptime_seconds=0.0
            )
            
            self.logger.info(f"📋 Component registered: {component_name}")
    
    def update_component_health(self, component_name: str, state: ComponentState,
                              error_message: str = None, performance_score: float = None):
        """Update component health status"""
        with self._master_lock:
            if component_name not in self.component_health:
                self.register_component(component_name)
            
            health = self.component_health[component_name]
            old_state = health.state
            
            # Update health information
            health.state = state
            health.last_heartbeat = datetime.now(timezone.utc)
            health.uptime_seconds = (health.last_heartbeat - self.system_start_time).total_seconds()
            
            if error_message:
                health.error_count += 1
                health.last_error = error_message
                self.component_errors[component_name].append({
                    'timestamp': datetime.now(timezone.utc),
                    'error': error_message
                })
            
            if performance_score is not None:
                health.performance_score = max(0.0, min(100.0, performance_score))
            
            # Log state changes
            if old_state != state:
                self.logger.info(f"🔧 Component {component_name}: {old_state.value} → {state.value}",
                               error_message=error_message)
            
            # Update overall system state
            self._update_overall_system_state()
    
    def component_heartbeat(self, component_name: str, metadata: Dict[str, Any] = None):
        """Update component heartbeat"""
        with self._master_lock:
            if component_name in self.component_health:
                health = self.component_health[component_name]
                health.last_heartbeat = datetime.now(timezone.utc)
                
                if metadata:
                    health.metadata.update(metadata)
    
    def get_component_health(self, component_name: str) -> Optional[ComponentHealth]:
        """Get health status for a component"""
        with self._master_lock:
            return self.component_health.get(component_name)
    
    def get_all_component_health(self) -> Dict[str, ComponentHealth]:
        """Get health status for all components"""
        with self._master_lock:
            return self.component_health.copy()
    
    def _update_overall_system_state(self):
        """Update overall system state based on component health"""
        
        if not self.component_health:
            return
        
        healthy_components = 0
        total_components = len(self.component_health)
        failed_components = 0
        
        for health in self.component_health.values():
            if health.state == ComponentState.HEALTHY:
                healthy_components += 1
            elif health.state == ComponentState.FAILED:
                failed_components += 1
        
        # Determine system state
        health_ratio = healthy_components / total_components
        
        if self.emergency_stop_active:
            new_state = SystemState.EMERGENCY
        elif failed_components > 0 and health_ratio < 0.5:
            new_state = SystemState.ERROR
        elif health_ratio < 0.8:
            new_state = SystemState.DEGRADED
        elif health_ratio >= 0.8:
            new_state = SystemState.HEALTHY
        else:
            new_state = SystemState.DEGRADED
        
        if new_state != self.system_state:
            self.set_system_state(new_state, f"Component health ratio: {health_ratio:.2f}")
    
    # ========================================================================
    # PERFORMANCE METRICS MANAGEMENT
    # ========================================================================
    
    def record_execution_start(self, execution_id: str, context: Dict[str, Any] = None):
        """Record execution start"""
        with self._master_lock:
            execution_info = {
                'execution_id': execution_id,
                'start_time': datetime.now(timezone.utc),
                'context': context or {},
                'status': 'running'
            }
            
            self.active_executions[execution_id] = execution_info
            self.execution_counters['total_executions'].increment()
    
    def record_execution_end(self, execution_id: str, success: bool, 
                           metrics: Dict[str, Any] = None):
        """Record execution completion"""
        with self._master_lock:
            if execution_id not in self.active_executions:
                return
            
            execution_info = self.active_executions.pop(execution_id)
            end_time = datetime.now(timezone.utc)
            execution_time = (end_time - execution_info['start_time']).total_seconds()
            
            # Update counters
            if success:
                self.execution_counters['successful_executions'].increment()
            else:
                self.execution_counters['failed_executions'].increment()
            
            # Record performance metrics
            self.performance_metrics.add_metric('execution_time', execution_time)
            
            # Store execution in history
            execution_info.update({
                'end_time': end_time,
                'execution_time': execution_time,
                'success': success,
                'status': 'completed' if success else 'failed',
                'metrics': metrics or {}
            })
            
            self.execution_history.append(execution_info)
    
    def record_performance_metric(self, name: str, value: float, 
                                component: str = None):
        """Record a performance metric"""
        self.performance_metrics.add_metric(name, value)
        
        if component:
            self.logger.performance(PerformanceMetric(
                metric_name=name,
                value=value,
                unit="unit",
                timestamp=datetime.now(timezone.utc),
                component=component
            ))
    
    def get_performance_summary(self, window_seconds: int = None) -> Dict[str, Any]:
        """Get comprehensive performance summary"""
        with self._master_lock:
            # Get execution statistics
            total_executions = self.execution_counters['total_executions'].get()
            successful_executions = self.execution_counters['successful_executions'].get()
            failed_executions = self.execution_counters['failed_executions'].get()
            
            success_rate = (successful_executions / total_executions * 100) if total_executions > 0 else 0
            
            # Get performance metrics
            metrics_summary = self.performance_metrics.get_all_metrics()
            
            # Get component health summary
            component_summary = {}
            for name, health in self.component_health.items():
                component_summary[name] = {
                    'state': health.state.value,
                    'performance_score': health.performance_score,
                    'error_count': health.error_count,
                    'uptime_seconds': health.uptime_seconds
                }
            
            return {
                'execution_statistics': {
                    'total_executions': total_executions,
                    'successful_executions': successful_executions,
                    'failed_executions': failed_executions,
                    'success_rate_percent': round(success_rate, 2),
                    'active_executions': len(self.active_executions)
                },
                'performance_metrics': metrics_summary,
                'component_health': component_summary,
                'system_uptime_seconds': (datetime.now(timezone.utc) - self.system_start_time).total_seconds(),
                'trading_state': self.trading_state.value,
                'system_state': self.system_state.value,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    # ========================================================================
    # TRADING SESSION MANAGEMENT
    # ========================================================================
    
    def start_trading_session(self, execution_mode: str) -> str:
        """Start a new trading session"""
        with self._master_lock:
            session_id = str(uuid.uuid4())
            
            self.current_session = TradingSession(
                session_id=session_id,
                start_time=datetime.now(timezone.utc),
                end_time=None,
                execution_mode=execution_mode,
                trades_executed=0,
                total_pnl=0.0,
                max_drawdown=0.0,
                active_positions=0
            )
            
            self.logger.info(f"📈 Trading session started: {session_id}",
                           execution_mode=execution_mode)
            
            return session_id
    
    def end_trading_session(self, pnl: float = 0.0):
        """End current trading session"""
        with self._master_lock:
            if not self.current_session:
                return
            
            self.current_session.end_time = datetime.now(timezone.utc)
            self.current_session.total_pnl = pnl
            
            # Store in history
            self.session_history.append(self.current_session)
            
            self.logger.info(f"📊 Trading session ended: {self.current_session.session_id}",
                           trades_executed=self.current_session.trades_executed,
                           total_pnl=pnl)
            
            self.current_session = None
    
    def update_session_metrics(self, trades_executed: int = 0, pnl_change: float = 0.0,
                              active_positions: int = None):
        """Update current session metrics"""
        with self._master_lock:
            if not self.current_session:
                return
            
            if trades_executed > 0:
                self.current_session.trades_executed += trades_executed
                self.execution_counters['trades_executed'].increment(trades_executed)
            
            if pnl_change != 0.0:
                self.current_session.total_pnl += pnl_change
                
                # Update max drawdown if negative
                if pnl_change < 0:
                    potential_drawdown = abs(self.current_session.total_pnl)
                    self.current_session.max_drawdown = max(
                        self.current_session.max_drawdown, 
                        potential_drawdown
                    )
            
            if active_positions is not None:
                self.current_session.active_positions = active_positions
    
    # ========================================================================
    # ERROR TRACKING AND RECOVERY
    # ========================================================================
    
    def record_error(self, component: str, error_message: str, 
                    error_type: str = "general", context: Dict[str, Any] = None):
        """Record system error"""
        with self._master_lock:
            error_info = {
                'timestamp': datetime.now(timezone.utc),
                'component': component,
                'error_type': error_type,
                'message': error_message,
                'context': context or {}
            }
            
            self.error_history.append(error_info)
            
            # Update component health
            self.update_component_health(
                component, 
                ComponentState.DEGRADED, 
                error_message
            )
            
            self.logger.error(f"🚨 Error recorded: {component} - {error_message}",
                            error_type=error_type, context=context)
    
    def get_error_summary(self, component: str = None, 
                         hours: int = 24) -> Dict[str, Any]:
        """Get error summary for analysis"""
        with self._master_lock:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            relevant_errors = [
                error for error in self.error_history
                if error['timestamp'] >= cutoff_time and
                (component is None or error['component'] == component)
            ]
            
            # Group by component and error type
            by_component = defaultdict(int)
            by_type = defaultdict(int)
            
            for error in relevant_errors:
                by_component[error['component']] += 1
                by_type[error['error_type']] += 1
            
            return {
                'total_errors': len(relevant_errors),
                'by_component': dict(by_component),
                'by_type': dict(by_type),
                'recent_errors': relevant_errors[-10:],  # Last 10 errors
                'time_window_hours': hours
            }
    
    # ========================================================================
    # ALERT MANAGEMENT
    # ========================================================================
    
    def add_alert(self, alert: SystemAlert):
        """Add system alert"""
        with self._master_lock:
            self.active_alerts[alert.alert_id] = alert
            self.alert_history.append(alert)
            self.execution_counters['alerts_generated'].increment()
            
            self.logger.warning(f"🚨 Alert generated: {alert.severity.value} - {alert.message}",
                              component=alert.component, alert_id=alert.alert_id)
    
    def resolve_alert(self, alert_id: str, resolution_note: str = None):
        """Resolve an active alert"""
        with self._master_lock:
            if alert_id in self.active_alerts:
                alert = self.active_alerts[alert_id]
                alert.resolved = True
                alert.resolution_time = datetime.now(timezone.utc)
                
                if resolution_note:
                    alert.metadata['resolution_note'] = resolution_note
                
                self.logger.info(f"✅ Alert resolved: {alert_id}",
                               resolution_note=resolution_note)
    
    def get_active_alerts(self, severity: AlertSeverity = None) -> List[SystemAlert]:
        """Get active alerts, optionally filtered by severity"""
        with self._master_lock:
            alerts = [alert for alert in self.active_alerts.values() if not alert.resolved]
            
            if severity:
                alerts = [alert for alert in alerts if alert.severity == severity]
            
            return sorted(alerts, key=lambda x: x.timestamp, reverse=True)
    
    # ========================================================================
    # RISK STATE MANAGEMENT
    # ========================================================================
    
    def check_risk_violation(self, risk_type: str, current_value: float, 
                           threshold: float) -> bool:
        """Check if a risk limit is violated"""
        
        violation = current_value > threshold
        
        if violation:
            with self._master_lock:
                violation_info = {
                    'timestamp': datetime.now(timezone.utc),
                    'risk_type': risk_type,
                    'current_value': current_value,
                    'threshold': threshold,
                    'severity': 'high' if current_value > threshold * 1.5 else 'medium'
                }
                
                self.risk_violations[risk_type].append(violation_info)
                
                # Generate alert for risk violation
                alert = SystemAlert(
                    alert_id=str(uuid.uuid4()),
                    severity=AlertSeverity.CRITICAL if current_value > threshold * 1.5 else AlertSeverity.WARNING,
                    component="risk_manager",
                    message=f"Risk limit violated: {risk_type} = {current_value:.2f} (limit: {threshold:.2f})",
                    timestamp=datetime.now(timezone.utc),
                    metadata=violation_info
                )
                
                self.add_alert(alert)
        
        return violation
    
    def get_risk_status(self) -> Dict[str, Any]:
        """Get current risk status"""
        with self._master_lock:
            recent_violations = {}
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            
            for risk_type, violations in self.risk_violations.items():
                recent = [v for v in violations if v['timestamp'] >= cutoff_time]
                if recent:
                    recent_violations[risk_type] = {
                        'count': len(recent),
                        'latest': recent[-1],
                        'severity': recent[-1]['severity']
                    }
            
            return {
                'risk_violations_24h': recent_violations,
                'emergency_stop_active': self.emergency_stop_active,
                'trading_state': self.trading_state.value,
                'risk_limits': asdict(self.risk_limits)
            }
    
    # ========================================================================
    # CONTEXT MANAGERS
    # ========================================================================
    
    @contextmanager
    def execution_context(self, execution_id: str, operation: str = None):
        """Context manager for execution tracking"""
        
        context = {'operation': operation} if operation else {}
        self.record_execution_start(execution_id, context)
        
        start_time = time.time()
        success = False
        
        try:
            yield
            success = True
        except Exception as e:
            self.record_error("execution", str(e), "execution_error", 
                            {'execution_id': execution_id, 'operation': operation})
            raise
        finally:
            execution_time = time.time() - start_time
            metrics = {'execution_time': execution_time}
            self.record_execution_end(execution_id, success, metrics)
    
    @contextmanager
    def component_operation(self, component: str, operation: str):
        """Context manager for component operations"""
        
        start_time = time.time()
        self.component_heartbeat(component, {'current_operation': operation})
        
        try:
            yield
        except Exception as e:
            self.update_component_health(component, ComponentState.DEGRADED, str(e))
            raise
        finally:
            execution_time = time.time() - start_time
            self.record_performance_metric(f"{component}_{operation}_time", execution_time, component)
            self.component_heartbeat(component, {'last_operation': operation})
    
    # ========================================================================
    # SYSTEM SUMMARY AND DIAGNOSTICS
    # ========================================================================
    
    def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        
        with self._master_lock:
            return {
                'instance_id': self.instance_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'uptime_seconds': (datetime.now(timezone.utc) - self.system_start_time).total_seconds(),
                
                'system_state': {
                    'overall': self.system_state.value,
                    'trading': self.trading_state.value,
                    'emergency_stop': self.emergency_stop_active,
                    'maintenance_mode': self.maintenance_mode
                },
                
                'component_health': {
                    name: {
                        'state': health.state.value,
                        'performance_score': health.performance_score,
                        'error_count': health.error_count,
                        'uptime_seconds': health.uptime_seconds
                    }
                    for name, health in self.component_health.items()
                },
                
                'performance_summary': self.get_performance_summary(),
                'error_summary': self.get_error_summary(),
                'risk_status': self.get_risk_status(),
                
                'current_session': asdict(self.current_session) if self.current_session else None,
                
                'active_alerts': [asdict(alert) for alert in self.get_active_alerts()],
                'active_executions': len(self.active_executions),
                
                'statistics': {
                    'total_executions': self.execution_counters['total_executions'].get(),
                    'successful_executions': self.execution_counters['successful_executions'].get(),
                    'failed_executions': self.execution_counters['failed_executions'].get(),
                    'api_calls': self.execution_counters['api_calls'].get(),
                    'trades_executed': self.execution_counters['trades_executed'].get(),
                    'alerts_generated': self.execution_counters['alerts_generated'].get()
                }
            }

# ============================================================================
# STATE MANAGEMENT EXCEPTIONS
# ============================================================================

class StateTransitionError(Exception):
    """Invalid state transition error"""
    pass

class ComponentNotFoundError(Exception):
    """Component not found error"""
    pass

# ============================================================================
# TESTING AND VALIDATION
# ============================================================================

def test_state_manager():
    """Test the state management system"""
    
    print("🧪 Testing Production State Manager...")
    
    try:
        # Mock config manager for testing
        class MockConfigManager:
            def get_risk_limits(self):
                from dataclasses import dataclass
                @dataclass
                class MockRiskLimits:
                    max_portfolio_loss_percent: float = 5.0
                    max_daily_loss_percent: float = 2.0
                    max_drawdown_percent: float = 15.0
                    max_single_position_percent: float = 12.0
                    max_sector_concentration_percent: float = 30.0
                    min_cash_percent: float = 3.0
                    max_tier3_allocation_percent: float = 15.0
                    position_correlation_limit: float = 0.8
                    volatility_threshold: float = 0.3
                    beta_limit: float = 2.0
                return MockRiskLimits()
        
        config_manager = MockConfigManager()
        state_manager = ProductionStateManager(config_manager)
        
        # Test component registration
        state_manager.register_component("test_component")
        state_manager.update_component_health("test_component", ComponentState.HEALTHY)
        print("✅ Component registration and health tracking")
        
        # Test trading state management
        state_manager.set_trading_state(TradingState.ENABLED, "Test activation")
        print("✅ Trading state management")
        
        # Test performance metrics
        with state_manager.execution_context("test_exec_001", "test_operation"):
            time.sleep(0.1)  # Simulate work
            state_manager.record_performance_metric("test_metric", 42.0, "test_component")
        print("✅ Performance metrics and execution tracking")
        
        # Test trading session
        session_id = state_manager.start_trading_session("test_mode")
        state_manager.update_session_metrics(trades_executed=5, pnl_change=150.0)
        state_manager.end_trading_session(150.0)
        print("✅ Trading session management")
        
        # Test error tracking
        state_manager.record_error("test_component", "Test error message", "test_error")
        print("✅ Error tracking")
        
        # Test alert management
        alert = SystemAlert(
            alert_id="test_alert_001",
            severity=AlertSeverity.WARNING,
            component="test_component",
            message="Test alert message",
            timestamp=datetime.now(timezone.utc)
        )
        state_manager.add_alert(alert)
        state_manager.resolve_alert("test_alert_001", "Test resolution")
        print("✅ Alert management")
        
        # Test risk violation checking
        violation = state_manager.check_risk_violation("test_risk", 15.0, 10.0)
        print(f"✅ Risk violation checking: {violation}")
        
        # Test comprehensive status
        status = state_manager.get_comprehensive_status()
        print(f"✅ Comprehensive status: {len(status)} sections")
        
        print("🎉 All state management tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ State management test failed: {e}")
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_state_manager()
