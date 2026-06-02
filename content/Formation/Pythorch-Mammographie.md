

**Titre GitHub :**  
**Breast Density Classification on VinDr-Mammo with PyTorch**

**Objectif :** entraîner un modèle simple pour prédire la **densité mammaire BI-RADS A/B/C/D** ou en version binaire **faible densité A-B vs forte densité C-D** à partir des mammographies VinDr-Mammo.

Pourquoi ce projet est bien pour toi : VinDr-Mammo est justement un dataset public de mammographie conçu pour l’évaluation du **BI-RADS** et de la **densité mammaire** au niveau du sein, avec aussi des annotations de lésions non bénignes. C’est directement lié à la thèse “breast cancer decision support”, qui parle d’imagerie, données cliniques, BI-RADS, densité mammaire et apprentissage ordinal.

## Version faisable en 7 à 10 jours

### MVP très réaliste

Tu fais un projet propre, pas trop ambitieux :

**Entrée :** mammographie VinDr-Mammo, idéalement une image par vue ou une image par sein.  
**Sortie :** classe de densité mammaire.  
**Modèle :** ResNet18 ou EfficientNet-B0 pré-entraîné.  
**Framework :** PyTorch + torchvision/timm.  
**Métriques :** accuracy, macro-F1, balanced accuracy, matrice de confusion.  
**Bonus médical :** séparation A/B vs C/D, car la densité élevée est cliniquement importante.

Un papier récent utilise justement VinDr-Mammo pour classifier la densité mammaire en binaire **low A/B vs high C/D**, ce qui valide que ce choix est pertinent et compréhensible pour un recruteur ou encadrant.

## Structure GitHub conseillée
vindr-mammo-density-classification/├── README.md├── requirements.txt├── configs/│   └── resnet18_density.yaml├── notebooks/│   └── 01_dataset_exploration.ipynb├── src/│   ├── dataset.py│   ├── preprocessing.py│   ├── model.py│   ├── train.py│   ├── evaluate.py│   └── utils.py├── reports/│   ├── confusion_matrix.png│   └── results.md└── .gitignore

Dans le README, mets clairement :

> This project explores breast density classification on VinDr-Mammo using PyTorch. It is intended as a reproducible baseline for medical imaging AI, with a focus on clinically meaningful evaluation, class imbalance and explainability.

## Étapes techniques

### 1. Télécharger et organiser les données

VinDr-Mammo est disponible publiquement via la page VinDr/PhysioNet, avec environ **5 000 examens** et un split mentionné de **4 000 examens train / 1 000 test**.

À faire :

- récupérer les images et annotations ;
- convertir les DICOM si nécessaire ;
- créer un CSV propre avec :
    - `image_id`
    - `study_id`
    - `laterality`
    - `view_position`
    - `density`
    - `birads`
    - `split`
    - `image_path`

### 2. Prétraitement image

Pour aller vite :

- convertir DICOM → PNG/JPEG 8-bit ou 16-bit ;
- redimensionner en **512×512** ou **768×768** ;
- normaliser ;
- éventuellement appliquer CLAHE, mais en bonus seulement ;
- garder la latéralité/vue dans le CSV.

Ne perds pas trop de temps sur le prétraitement parfait : pour un projet GitHub, ce qui compte est d’avoir une pipeline claire et reproductible.

### 3. Modèle PyTorch

Commence simple :

- `ResNet18 pretrained=True`
- adapter la dernière couche à 4 classes ou 2 classes ;
- loss : `CrossEntropyLoss`
- optimizer : AdamW
- scheduler : cosine ou ReduceLROnPlateau

Pour le déséquilibre de classes :

- `WeightedRandomSampler`, ou
- `class_weight` dans la loss, ou
- focal loss en bonus.

### 4. Évaluation

Fais une évaluation propre :

- accuracy globale ;
- macro-F1 ;
- balanced accuracy ;
- matrice de confusion ;
- AUC si binaire A/B vs C/D ;
- analyse des erreurs par vue, par densité, éventuellement par BI-RADS.

Ce qui fera sérieux : montrer que tu comprends que l’accuracy seule est insuffisante en médical.

## Projet bonus après MVP

Après le premier projet, tu peux ajouter un deuxième niveau plus aligné avec la thèse :

### Bonus 1 — apprentissage ordinal

Au lieu de traiter A/B/C/D comme 4 classes indépendantes, tu expliques que la densité mammaire est **ordonnée**. Tu peux tester :

- classification 4 classes classique ;
- régression ordinale ;
- ou pénalité plus forte quand le modèle confond A avec D plutôt que C avec D.

C’est très pertinent, car la thèse mentionne explicitement l’**ordinal-aware representation learning** pour des scores comme BI-RADS et tumour grades.

### Bonus 2 — Grad-CAM

Ajoute une visualisation Grad-CAM sur quelques cas :

- prédiction correcte ;
- erreur proche ;
- erreur importante.

Ça montre que tu sais aller au-delà de “j’ai entraîné un modèle” et que tu penses interprétabilité clinique.

### Bonus 3 — multimodal tabulaire simple

Si les annotations contiennent des variables exploitables, tu peux faire un mini-modèle :

- branche image ResNet ;
- branche tabulaire MLP ;
- fusion des embeddings ;
- prédiction densité ou BI-RADS.

Même simple, ça te rapproche directement du sujet de thèse : **image + données cliniques/tabulaires**.

## Ce que tu peux écrire dans ta candidature après le projet

> To strengthen my application, I have started a PyTorch project on VinDr-Mammo focused on breast density classification from mammography images. The project includes a reproducible preprocessing pipeline, a ResNet/EfficientNet baseline, class imbalance handling, clinically relevant metrics, and an initial exploration of ordinal labels and explainability with Grad-CAM.

## Recommandation finale

Fais ce projet en **PyTorch**, avec un objectif simple :

**Semaine 1 : classification densité A/B/C/D ou A-B vs C-D.**  
**Semaine 2 : Grad-CAM + version ordinale + README propre.**

C’est le meilleur ratio temps/impact pour toi : ça relie ton expérience en imagerie médicale à une preuve concrète de montée en compétence IA.