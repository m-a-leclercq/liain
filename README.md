# Suivi du déploiement de la fibre dans l'Ain

## Injection des données
La récupération des données est assurée par `dl_schedule.sh` qui est croné à 1h chaque matin. Ce script lance `liain.py` qui récupère la dernière version de l'IPE à jour , l'extrait, recalcule les positions GPS en format lat,lon classique, puis dépose le fichier retravaillé dans un répertoire surveillé par un filebeat avec un `filestream` input appelant le pipeline `ingest_liain.json`.

## Découpage des données
La mise en forme des données est assurée par l'ingest pipeline `ingest_liain.json` ainsi que le component template `liain_component` qui stocke les champs comme `DateMADPM`en type `date` afin de les requêter correctement via Elastic.

## Statistiques
Les transform créent automatiquement des stats des déploiements à deux niveaux:
- Nombre d'immeubles et leurs statuts par rapport au total d'une commune (`SIGNE`, `CIBLE`, `EN COURS` puis `DEPLOYE` )
- Nombres de PM et leur statuts par rapport au total d'une commune (attention, un PM d'une commune peut desservir des immeubles d'une autre commune). `EN COURS DE DEPLOIEMENT` ou `DEPLOYE`


## Remerciements
[Simon blum](simon@blum.dev) Pour l'écriture du code de conversion des projections GPS et son aide à la compréhension des informations de l'IPE.
