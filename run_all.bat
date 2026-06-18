@echo off
rem Run all tests in the MoleditPy workspace using python runner
python "%~dp0run_all_tests.py" %*
exit /b %errorlevel%
