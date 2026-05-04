#!/bin/bash

# Start both dashboards (Water Velocity and Opta JSON)
# Usage: ./startdashboards.sh
# Kill with: Ctrl+C (both processes will be terminated)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if venv exists
if [ ! -f ".venv/bin/activate" ]; then
    echo "Error: Virtual environment not found at .venv/bin/activate"
    echo "Please create it first with: python3 -m venv .venv"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Clear old log files
rm -f dashboard.log opta_dashboard.log

echo "Starting dashboards in RadarSensor repository..."
echo ""

# Start Water Velocity Dashboard
python dashboard.py > dashboard.log 2>&1 &
PID1=$!
echo "✓ Water Velocity Dashboard started (PID $PID1)"

# Start Opta JSON Dashboard
python opta_dashboard.py > opta_dashboard.log 2>&1 &
PID2=$!
echo "✓ Opta JSON Dashboard started (PID $PID2)"

echo ""
echo "======================================"
echo "Water dashboard: http://localhost:5000  (PID $PID1)"
echo "Opta dashboard:  http://localhost:5051  (PID $PID2)"
echo "======================================"
echo ""
echo "Log files:"
echo "  - dashboard.log (Water Velocity)"
echo "  - opta_dashboard.log (Opta)"
echo ""
echo "Press Ctrl+C to stop both dashboards..."
echo ""

# Set up trap to kill both processes on exit
trap "
    echo ''
    echo 'Shutting down dashboards...'
    kill $PID1 $PID2 2>/dev/null || true
    echo 'Dashboards stopped.'
    exit 0
" INT TERM

# Wait for both processes
wait
