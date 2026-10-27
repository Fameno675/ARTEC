INITIAL_CRITERIA = [
    # (code, category, label, description)
    ("mobile_data_speed", "mobile_data", "Internet mobile : vitesse", "Vitesse ressentie de téléchargement."),
    ("mobile_data_stability", "mobile_data", "Internet mobile : stabilité", "Stabilité de la connexion."),
    ("mobile_data_availability", "mobile_data", "Internet mobile : disponibilité", "Disponibilité de la connexion."),
    ("call_audio_quality", "calls", "Appels : qualité sonore", "Qualité sonore des appels."),
    ("call_success_stability", "calls", "Appels : réussite et stabilité", "Réussite et stabilité des appels."),
    ("sms_reliability", "sms", "SMS : fiabilité et rapidité", "Fiabilité et rapidité de réception."),
    ("pricing_value", "pricing", "Tarification : rapport qualité-prix", "Rapport qualité-prix des forfaits."),
    ("credit_purchase_ease", "credit_plans", "Crédit et forfaits : facilité", "Facilité d'achat et de renouvellement."),
    ("mobile_money_reliability", "mobile_money", "Mobile money : fiabilité", "Fiabilité des transactions."),
    ("customer_service", "customer_service", "Service client", "Rapidité et qualité de l'assistance."),
]

DEFAULT_SURVEY = {
    "slug": "satisfaction-generale",
    "title": "Qualité des services mobiles",
    "description": "Évaluez votre opérateur de 0 (très mauvais) à 10 (excellent). Aucune donnée personnelle n'est demandée.",
}
