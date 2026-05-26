# Job Watch Obsidian

Ce kit surveille des entreprises/labos via :
- recherches RSS Bing ;
- sites carrière directs ajoutés dans `organizations.csv` ;
- job boards/ATS indexés : LinkedIn Jobs, Indeed, Welcome to the Jungle, APEC, EURAXESS, Academic Positions, Lever, Greenhouse, Workday, SmartRecruiters, Ashby, etc.

## Installation

1. Dézippe ce dossier, par exemple dans :
   `C:\Users\GOULWEN\Documents\Second_brain\job_watch`

2. Ouvre PowerShell dans ce dossier.

3. Lance :
   `.\install_and_run.ps1`

Le rapport sera écrit dans :
`C:\Users\GOULWEN\Documents\Second_brain\quartz\content\Jobs\Veille automatique`

## Ajouter des pages carrière directes

Dans `organizations.csv`, remplis la colonne `direct_url` pour les pages que tu veux surveiller directement.

Exemple :
- `https://jobs.lever.co/...`
- `https://boards.greenhouse.io/...`
- `https://careers.company.com/...`
- `https://www.institut.fr/recrutement`

## Planification quotidienne Windows

Ouvre le Planificateur de tâches Windows et crée une tâche quotidienne.

Programme :
`powershell.exe`

Arguments :
`-ExecutionPolicy Bypass -File "C:\Users\GOULWEN\Documents\Second_brain\job_watch\run_daily.ps1"`

Crée aussi un fichier `run_daily.ps1` contenant :

```powershell
cd "C:\Users\GOULWEN\Documents\Second_brain\job_watch"
.\.venv\Scripts\Activate.ps1
python .\job_watch.py
```
