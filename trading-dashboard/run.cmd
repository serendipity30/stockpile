@echo on

cd /d "D:\git_repo\stockpile\trading-dashboard"
call .venv\Scripts\activate

echo "Starting Trading Dashboard at http://localhost:5000"
python3 app.py

pause