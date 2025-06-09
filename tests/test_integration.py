#!/usr/bin/env python3
"""
Integration test for complete trading system
"""

import json
import boto3
import requests
from datetime import datetime

def test_trading_system(function_name, region='us-east-1'):
    """Test all trading system components"""
    
    print("🧪 Testing Complete Trading System")
    print("=" * 50)
    
    lambda_client = boto3.client('lambda', region_name=region)
    
    # Test 1: Health Check
    print("\n1. 🏥 Health Check Test")
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({
                "path": "/health",
                "httpMethod": "GET"
            })
        )
        
        result = json.loads(response['Payload'].read())
        print(f"   Status: {result.get('statusCode', 'Unknown')}")
        
        if result.get('statusCode') == 200:
            body = json.loads(result.get('body', '{}'))
            print(f"   System State: {body.get('system_status', {}).get('system_state', 'Unknown')}")
            print("   ✅ Health Check PASSED")
        else:
            print("   ❌ Health Check FAILED")
            
    except Exception as e:
        print(f"   ❌ Health Check ERROR: {e}")
    
    # Test 2: Trading Cycle Execution
    print("\n2. 🎯 Trading Cycle Test")
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({
                "source": "manual_test",
                "mode": "trading_cycle"
            })
        )
        
        result = json.loads(response['Payload'].read())
        print(f"   Status: {result.get('statusCode', 'Unknown')}")
        
        if result.get('statusCode') == 200:
            body = json.loads(result.get('body', '{}'))
            summary = body.get('summary', {})
            print(f"   Components Executed: {summary.get('components_executed', 0)}")
            print(f"   Execution Time: {summary.get('execution_time', 0):.2f}s")
            print("   ✅ Trading Cycle PASSED")
        else:
            print("   ❌ Trading Cycle FAILED")
            
    except Exception as e:
        print(f"   ❌ Trading Cycle ERROR: {e}")
    
    # Test 3: AI Analysis Test
    print("\n3. 🧠 AI Analysis Test")
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({
                "source": "manual_test",
                "mode": "ai_analysis",
                "symbol": "AAPL"
            })
        )
        
        result = json.loads(response['Payload'].read())
        print(f"   Status: {result.get('statusCode', 'Unknown')}")
        
        if result.get('statusCode') == 200:
            print("   ✅ AI Analysis PASSED")
        else:
            print("   ❌ AI Analysis FAILED")
            
    except Exception as e:
        print(f"   ❌ AI Analysis ERROR: {e}")
    
    print(f"\n🎉 Integration Test Complete!")
    print(f"Timestamp: {datetime.now().isoformat()}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python test_integration.py <function_name>")
        sys.exit(1)
    
    function_name = sys.argv[1]
    test_trading_system(function_name)
