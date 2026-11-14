@echo off
REM Copia de seguridad de la base de datos y las fotos (deja los ultimos 30).
REM Para que sea diario: Programador de tareas de Windows -> Crear tarea basica -> Diariamente -> Iniciar un programa -> este archivo.
REM Para guardarlo en otro lugar (USB, Google Drive, OneDrive):  respaldo.bat "D:\Respaldos"
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
if "%~1"=="" (python manage.py respaldo) else (python manage.py respaldo --carpeta "%~1")
