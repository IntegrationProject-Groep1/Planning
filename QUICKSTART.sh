#!/usr/bin/env bash
# Quick Start Guide for Planning Service

echo "📋 Planning Service - Quick Start"
echo "=================================="
echo ""

# Check Python
echo "✓ Checking Python..."
python --version

# Check Docker
echo "✓ Checking Docker..."
docker --version

echo ""
echo "🚀 Starting Services..."
echo ""

# Option 1: Local with RabbitMQ
echo "Option 1: Local Development (includes RabbitMQ)"
echo "$env:ENV_FILE='.env.local'; docker compose --profile local up -d"
echo ""

# Option 2: Production
echo "Option 2: Production (remote RabbitMQ)"
echo "docker compose up -d"
echo ""

echo "📝 After Starting:"
echo "1. Wait 10 seconds for services to initialize"
echo "2. Check logs: docker compose logs -f planning-service"
echo "3. Access RabbitMQ: http://localhost:15672 (guest:guest)"
echo "4. Access pgAdmin: http://localhost:5050"
echo ""

echo "🧪 Running Tests:"
echo "pip install -r requirements.txt"
echo "pytest tests/ -v"
echo ""

echo "📡 Publishing Test Messages:"
echo "python producer.py created"
echo "python producer.py updated"
echo "python producer.py deleted"
echo "python producer.py response"
echo ""

echo "📊 Database Queries:"
echo "docker compose exec db psql -U planning_user -d planning_db"
echo "SELECT * FROM sessions;"
echo "SELECT * FROM message_log;"
echo ""

echo "✅ Quick Setup Complete!"
