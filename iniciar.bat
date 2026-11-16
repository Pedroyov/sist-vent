@echo off
REM Abre el sistema con la base REAL del negocio (db.sqlite3) para esta PC y los celulares del mismo WiFi.
REM Deja esta ventana abierta mientras se trabaja. Para apagar: Ctrl+C o cerrar la ventana.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
echo Copia de seguridad antes de empezar...
python manage.py respaldo || echo (No se pudo hacer la copia de seguridad, revisa el mensaje de arriba)
echo Revisando la base de datos...
python manage.py migrate -v0 || goto :error
set ALLOWED_HOSTS=*
set IP=
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1).IPv4Address.IPAddress"`) do set IP=%%i
echo.
echo  ==============================================================
echo   SISTEMA DE VENTAS - deja esta ventana abierta
echo  ==============================================================
echo   En esta PC:      http://127.0.0.1:8000
if defined IP echo   En celulares:    http://%IP%:8000   (conectados al mismo WiFi)
if not defined IP echo   En celulares: escribe ipconfig en otra ventana y usa la "Direccion IPv4" con :8000
echo   Si Windows pregunta por el firewall, marca "Redes privadas" y pulsa Permitir.
echo  ==============================================================
echo.
python manage.py runserver 0.0.0.0:8000
goto :eof
:error
echo Hubo un error. Revisa el mensaje de arriba.
pause
