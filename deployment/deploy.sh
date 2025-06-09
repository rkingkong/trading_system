#!/bin/bash

# Trading System Deployment Script
set -e

echo "🚀 Deploying Enterprise Trading System to AWS Lambda..."

# Configuration
ENVIRONMENT=${1:-production}
STACK_NAME="trading-system-${ENVIRONMENT}"
REGION="us-east-1"

echo "Environment: $ENVIRONMENT"
echo "Stack Name: $STACK_NAME"
echo "Region: $REGION"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install AWS CLI."
    exit 1
fi

# Check SAM CLI
if ! command -v sam &> /dev/null; then
    echo "❌ SAM CLI not found. Please install SAM CLI."
    exit 1
fi

# Check if logged into AWS
aws sts get-caller-identity > /dev/null 2>&1 || {
    echo "❌ Not logged into AWS. Please run 'aws configure'."
    exit 1
}

echo "✅ Prerequisites verified"

# Build the application
echo "🔨 Building SAM application..."
sam build --use-container

# Deploy the application
echo "🚀 Deploying to AWS..."
sam deploy \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        Environment="$ENVIRONMENT" \
        NotificationEmail="rkong@armku.us" \
    --confirm-changeset

# Get the outputs
echo "📋 Deployment Information:"
aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs' \
    --output table

# Test the deployment
echo "🧪 Testing deployment..."
FUNCTION_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`TradingSystemFunctionArn`].OutputValue' \
    --output text | cut -d':' -f7)

# Invoke health check
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"path": "/health", "httpMethod": "GET"}' \
    --cli-binary-format raw-in-base64-out \
    response.json

echo "✅ Health check response:"
cat response.json | python3 -m json.tool
rm response.json

echo ""
echo "🎉 DEPLOYMENT COMPLETE!"
echo "Monitor your trading system at:"
echo "https://${REGION}.console.aws.amazon.com/lambda/home?region=${REGION}#/functions/${FUNCTION_NAME}"
