@echo off
REM Reenvia a SUNAT los comprobantes que quedaron pendientes (por ejemplo, por falta de internet).
REM Para que sea automatico: Programador de tareas de Windows -> Crear tarea basica -> Diariamente -> repetir cada 1 hora -> Iniciar un programa -> este archivo.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python manage.py reenviar_comprobantes
