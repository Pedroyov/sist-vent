@echo off
REM Abre el sistema con DATOS DE EJEMPLO en una base aparte (db_demo.sqlite3).
REM Tu base real (db.sqlite3) no se toca.
REM   demo.bat          solo en esta PC
REM   demo.bat red      tambien desde celulares conectados al mismo WiFi
REM   demo.bat nuevo    vuelve a generar los datos de ejemplo (se puede combinar: demo.bat nuevo red)
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
set DATABASE_URL=sqlite:///db_demo.sqlite3
set NUEVO=
set RED=
for %%a in (%*) do (
  if /i "%%a"=="nuevo" set NUEVO=1
  if /i "%%a"=="red" set RED=1
)
if defined NUEVO if exist db_demo.sqlite3 del db_demo.sqlite3
if not exist db_demo.sqlite3 (
  echo Creando la base de ejemplo, espera unos segundos...
  python manage.py migrate -v0 || goto :error
  python manage.py datos_demo || goto :error
)
echo.
if defined RED goto :red
echo  Abre http://127.0.0.1:8000  (usuario: director  clave: demo1234)
echo  Para volver a generar los datos: demo.bat nuevo
echo  Para abrirlo tambien desde un celular: demo.bat red
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
echo  Usuario: director  clave: demo1234
echo.
python manage.py runserver 0.0.0.0:8000
goto :eof
:error
echo Hubo un error. Revisa el mensaje de arriba.
pause
