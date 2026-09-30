@echo off
rem Fotojaar voor Windows: dubbelklik dit bestand. Het installeert wat nodig is (Python, Pillow, openpyxl)
rem en toont een menu, zodat je zelf geen commando's hoeft te typen.
rem Optioneel: Fotojaar.cmd pad\naar\config.json  werkt met een andere instantie.
setlocal EnableExtensions
chcp 65001 >nul
title Fotojaar
cd /d "%~dp0"
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "BUILD=%ROOT%tools\build.py"
if not "%~1"=="" set "FOTOJAAR_CONFIG=%~f1"
if defined FOTOJAAR_CONFIG (set "CFGFILE=%FOTOJAAR_CONFIG%") else set "CFGFILE=%ROOT%tools\config.json"

if exist "%VPY%" goto deps

rem ---- Python zoeken (of installeren) ------------------------------------------------
:findpy
set "PY="
call :trypy py -3
if not defined PY call :trypy python
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PY if exist "%%D\python.exe" call :trypy "%%D\python.exe"
if not defined PY for /d %%D in ("%ProgramFiles%\Python3*") do if not defined PY if exist "%%D\python.exe" call :trypy "%%D\python.exe"
if defined PY goto makevenv
if defined TRIED goto nopython
set "TRIED=1"
echo.
echo Python (versie 3.9 of nieuwer) is niet gevonden op deze computer.
where winget >nul 2>&1
if errorlevel 1 goto nowinget
set /p "A=Zal ik Python nu voor je installeren? Dat duurt een paar minuten. (J/N) "
if /i not "%A%"=="J" goto nopython
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
goto findpy

:nowinget
echo.
echo Installeer Python zelf via https://www.python.org/downloads/ (vink "Add python.exe to PATH" aan)
echo en dubbelklik daarna opnieuw op Fotojaar.cmd.
start "" https://www.python.org/downloads/
goto einde

:nopython
echo.
echo Python is niet beschikbaar. Installeer het via https://www.python.org/downloads/
echo (vink "Add python.exe to PATH" aan) en dubbelklik daarna opnieuw op Fotojaar.cmd.
goto einde

:makevenv
echo.
echo Eerste keer: Fotojaar wordt klaargezet (Python: %PY%)
"%PY%" -m venv "%VENV%"
if errorlevel 1 (
  echo Kon de omgeving niet aanmaken.
  rd /s /q "%VENV%" >nul 2>&1
  goto einde
)

rem ---- Onderdelen installeren (enkel als requirements.txt nieuw of gewijzigd is) ----------
:deps
fc /b "%ROOT%requirements.txt" "%VENV%\requirements.installed" >nul 2>&1
if not errorlevel 1 goto menu
echo.
echo Onderdelen installeren, even geduld...
"%VPY%" -m pip install --disable-pip-version-check -q -r "%ROOT%requirements.txt"
if errorlevel 1 (
  echo.
  echo Installeren mislukt. Ben je verbonden met het internet? Probeer het daarna opnieuw.
  goto einde
)
copy /y "%ROOT%requirements.txt" "%VENV%\requirements.installed" >nul

rem ---- Menu ----------------------------------------------------------------------------
:menu
cls
echo.
echo   FOTOJAAR
echo   ========
if not exist "%CFGFILE%" (
  echo   Nog niet ingesteld: begin met 2, of bekijk eerst de demo met 1.
) else (
  echo   Ingesteld: %CFGFILE%
)
echo.
echo    1  Demo bekijken
echo    2  Instellen ^(map met foto's, taal, titel^)
echo    3  Installatie en collectie controleren
echo    4  Foto's inlezen ^(scan; alleen als de jaartallen in de metadata staan^)
echo    5  Lijst photos.csv maken ^(alleen als de jaartallen in een lijst komen^)
echo    6  Foto's kiezen en nakijken ^(opent een pagina in je browser^)
echo    7  Verhalen schrijven ^(opent een pagina in je browser^)
echo    8  Website maken
echo    9  Publiceren
echo    E  exiftool installeren ^(alleen nodig voor jaartallen in de metadata^)
echo    0  Stoppen
echo.
choice /c 123456789E0 /n /m "  Kies een nummer: "
set "K=%errorlevel%"
if "%K%"=="1" goto demo
if "%K%"=="2" call :run setup & goto menu
if "%K%"=="3" call :run check & goto menu
if "%K%"=="4" call :run scan & goto menu
if "%K%"=="5" call :run init-csv & goto menu
if "%K%"=="6" call :serve analyze & goto menu
if "%K%"=="7" call :serve verhalen & goto menu
if "%K%"=="8" call :run build & goto menu
if "%K%"=="9" call :run publish & goto menu
if "%K%"=="10" goto exif
goto einde

:run
echo.
"%VPY%" "%BUILD%" %*
echo.
pause
exit /b

rem De controle- en verhalenpagina draaien in een eigen venster tot je dat sluit (of Ctrl+C drukt).
:serve
echo.
echo Er opent een nieuw venster en de pagina verschijnt in je browser.
echo Klaar? Klik op de pagina op Bewaar, sluit daarna het nieuwe venster en kies hier verder.
start "Fotojaar - %*" /wait cmd /c ""%VPY%" "%BUILD%" %* ^& pause"
exit /b

:demo
if not exist "%ROOT%demo\config.json" (
  echo.
  "%VPY%" "%BUILD%" demo
  if errorlevel 1 (echo. & pause & goto menu)
)
echo.
echo De demo staat op http://localhost:8000 en opent in je browser.
echo Sluit het nieuwe venster als je klaar bent.
start "" http://localhost:8000
start "Fotojaar - demo" /wait cmd /c ""%VPY%" -m http.server 8000 --bind 127.0.0.1 --directory "%ROOT%demo\dist""
goto menu

:exif
echo.
where winget >nul 2>&1
if errorlevel 1 (
  echo winget ontbreekt: download exiftool op https://exiftool.org
  start "" https://exiftool.org
) else (
  winget install --id OliverBetz.ExifTool -e --accept-package-agreements --accept-source-agreements
  echo.
  echo Sluit Fotojaar en start het opnieuw, zodat exiftool gevonden wordt.
)
echo.
pause
goto menu

rem ---- Hulp: is %* een Python 3.9+? Zo ja, zet PY op het volledige pad --------------------
:trypy
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 exit /b
%* -c "import sys; open(sys.argv[1], 'w').write(sys.executable)" "%TEMP%\fotojaar-py.txt" >nul 2>&1
if errorlevel 1 exit /b
set /p PY=<"%TEMP%\fotojaar-py.txt"
del "%TEMP%\fotojaar-py.txt" >nul 2>&1
exit /b

:einde
echo.
pause
endlocal
