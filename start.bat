@echo off
echo ============================================================
echo    Semantic Video Synthesizer - Presentation Startup
echo ============================================================
echo.

:: Check if Redis is running (Ollama and Redis must be pre-started)
echo [1/3] Starting FastAPI Backend...
start "SVS Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend to start
timeout /t 5 /nobreak > nul

echo [2/3] Starting Celery Worker...
start "SVS Celery" cmd /k "cd /d %~dp0backend && python start_celery.py -A services.task_orchestrator.celery_app worker --pool=threads --concurrency=2 --loglevel=info"

:: Wait for Celery to start
timeout /t 3 /nobreak > nul

echo [3/3] Starting Frontend...
start "SVS Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

:: Wait and open browser
timeout /t 6 /nobreak > nul
echo.
echo ============================================================
echo    App ready at: http://localhost:3000
echo    Backend API:  http://localhost:8000/docs
echo ============================================================
echo.
echo Requirements before starting:
echo   - Redis: should be running (redis-server or WSL)
echo   - Ollama: should be running (ollama serve)
echo.
start http://localhost:3000

pause
