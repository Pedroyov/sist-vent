@echo off
REM Abre una DEMO con datos de ejemplo, igual que las demos de Render. Hay una base por tipo de negocio
REM (db_demo_tie.sqlite3, db_demo_pel.sqlite3...): cambiar de negocio no borra las otras. Tu base real (db.sqlite3) no se toca.
REM   demo.bat            tienda / bodega
REM   demo.bat pel        peluqueria  (tie tienda, res restaurante, rop ropa, lib libreria, pel peluqueria, aca academia o gimnasio)
REM   demo.bat pel nuevo  vuelve a generar los datos de ejemplo de ese negocio (con las fechas de hoy)
REM   demo.bat pel red    tambien desde celulares conectados al mismo WiFi
REM Se abre una demo a la vez. Como en Render, no se pueden cambiar claves, usuarios ni modulos.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
set NUEVO=
set RED=
set RUBRO=TIE
for %%a in (%*) do (
  if /i "%%a"=="nuevo" set NUEVO=1
  if /i "%%a"=="red" set RED=1
  if /i "%%a"=="tie" set RUBRO=TIE
  if /i "%%a"=="res" set RUBRO=RES
  if /i "%%a"=="rop" set RUBRO=ROP
  if /i "%%a"=="lib" set RUBRO=LIB
  if /i "%%a"=="pel" set RUBRO=PEL
  if /i "%%a"=="aca" set RUBRO=ACA
)
set BASE=db_demo_%RUBRO%.sqlite3
set DATABASE_URL=sqlite:///%BASE%
set DEMO=True
pip install -q --disable-pip-version-check -r requirements.txt || echo (No se pudo instalar algo de requirements.txt: revisa el internet)
if defined NUEVO if exist %BASE% del %BASE%
if not exist %BASE% (
  echo Creando la demo %RUBRO%, espera unos segundos...
  python manage.py migrate -v0 || goto :error
  python manage.py datos_demo --rubro %RUBRO% || goto :error
) else (
  python manage.py migrate -v0 || goto :error
)
echo.
echo  Demo %RUBRO% (base %BASE%). Los usuarios de prueba aparecen al ingresar (clave demo1234).
echo  Para volver a generarla con las fechas de hoy: demo.bat %RUBRO% nuevo
if defined RED goto :red
echo  Abre http://127.0.0.1:8000
echo.
python manage.py runserver
goto :eof
:red
set ALLOWED_HOSTS=*
set IP=
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1).IPv4Address.IPAddress"`) do set IP=%%i
echo  En esta PC:        http://127.0.0.1:8000
if defined IP echo  En el celular:     http://%IP%:8000   (mismo WiFi o datos compartidos desde tu celular)
if not defined IP echo  En el celular: escribe ipconfig en otra ventana y usa la "Direccion IPv4" con :8000
echo  Si Windows pregunta por el firewall, marca "Redes privadas" y pulsa Permitir.
echo.
python manage.py runserver 0.0.0.0:8000
goto :eof
:error
echo Hubo un error. Revisa el mensaje de arriba.
pause
