# install_and_run.ps1
# À lancer dans PowerShell depuis le dossier contenant job_watch.py

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\job_watch.py
