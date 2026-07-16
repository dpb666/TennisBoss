"""Constantes de version pour la reproductibilité des picks loggés.

Bump manuel (pas un numéro de release semver automatique) quand la
structure change : PREDICTOR_VERSION quand predictor.py change sa formule
de score/logit ou son usage de l'ELO ; FEATURE_SET_VERSION quand
config.FEATURE_ORDER ou le schéma de profil (bot/features.py) change ;
CALIBRATION_VERSION quand la MÉTHODE de calibration change (ex. Platt
remplacé par autre chose — pas quand seuls les paramètres k/a/b appris
changent, ceux-là sont déjà loggés en clair par pick, voir clv_log.calib_k).

Sert à répondre, en ré-analysant un pick loggé il y a des mois : "avec
quelle version du pipeline ce pick a-t-il été produit ?" — sans ça, un
changement de méthode de calibration ou de jeu de features rend les
anciens picks silencieusement incomparables aux nouveaux.
"""
PREDICTOR_VERSION = "1.0"
FEATURE_SET_VERSION = "1.0"
CALIBRATION_VERSION = "1.0"
