@echo off
echo ========================================
echo  VarisAcademy — Yerli AI Qurulumu
echo  RTX 3080 + Ollama + Llama 3.1 8B
echo ========================================
echo.

REM 1. Ollama yoxla
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Ollama tapilmadi!
    echo [!] https://ollama.com/download saytindan yukle ve qurast
    echo [!] Sonra bu skripti yeniden islet.
    pause
    exit /b 1
)

echo [OK] Ollama tapildi

REM 2. Ollama servisini baslat
echo [..] Ollama servisi basladilir...
start /B ollama serve
timeout /t 3 /nobreak >nul

REM 3. Llama 3.1 8B yukle (GPU - RTX 3080)
echo [..] Llama 3.1 8B yuklenir (ilk defe ~5GB, sonraki ishlemelerde yox)...
ollama pull llama3.1:8b

REM 4. Embedding modeli yukle
echo [..] nomic-embed-text (embedding) yuklenir (~274MB)...
ollama pull nomic-embed-text

REM 5. Python paketleri
echo [..] Python paketleri qurashdirilir...
pip install chromadb==0.5.23 sentence-transformers==3.3.1

echo.
echo ========================================
echo  [TAMAM] AI sistemi hazirdir!
echo.
echo  Modeller:
echo    llama3.1:8b     - Azerbaycan dili, tehsil AI
echo    nomic-embed-text - RAG embedding
echo.
echo  Backend-i yeniden baslat:
echo    uvicorn app.main:app --reload --port 8001
echo ========================================
pause
