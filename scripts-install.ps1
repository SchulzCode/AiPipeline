$ErrorActionPreference = "Stop"
python -m pip install -e .
aipipe doctor
Write-Host "AIpipe installed. Run: aipipe --repo C:\path\to\project doctor"
