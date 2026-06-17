
Sortie du custom 3D SWE, carte de deformations du tissus ou deja calcul de vitesse des ondes de cisaillements? 

données RF ?
données IQ ?
volumes beamformés ?
champs de déplacement ?
cartes préliminaires ?
synchronisation ECG ?

## définir la sortie attendue

Décider ce que le modèle doit produire : 3D shear wave velocity (SWV) estimation based on 3D elastic wave propagation


+ entraînement sur données in vitro  ?
+ validation sur in vivo ? Comment valider données in vivo ? Comment carte rigidité ou vitesse ondes cisaillements est defini ? 
Donc la validation in vivo consiste plutôt à vérifier que la méthode produit des résultats :

```
reproductibles,physiquement cohérents,compatibles avec la physiologie cardiaque,corrélés à des données cliniques,capables de distinguer des groupes pathologiques.
```

Ce n’est pas une validation “vérité terrain parfaite”, c’est une validation de **crédibilité scientifique et clinique**.

1. Acquisition 3D SWE sur fantôme ou patient
2. Reconstruction de volumes ultrasonores
3. Estimation des micro-déplacements u(x,y,z,t)
4. Nettoyage / filtrage / sélection des zones exploitables
5. Synchronisation avec ECG
6. Construction d’un dataset deep learning
7. Développement d’un PINN
8. Apprentissage de la propagation 3D
9. Estimation de la carte SWV
10. Validation in vitro
11. Validation in vivo
12. Analyse de variation pendant le cycle cardiaque
13. Extraction de biomarqueurs
14. Intégration possible dans un modèle diagnostic

https://pubmed.ncbi.nlm.nih.gov/26067040/

https://pubmed.ncbi.nlm.nih.gov/32857692/


Loss_data :
le déplacement prédit ressemble au déplacement mesuré

Loss_wave :
le déplacement prédit respecte l’équation d’onde

Loss_smooth :
la carte de vitesse ne varie pas de manière absurde entre voxels voisins

Loss_boundary :
conditions aux limites ou contraintes anatomiques

