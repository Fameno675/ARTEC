"""Données initiales idempotentes (utilisées par la migration et testables seules)."""

INITIAL_OPERATORS = [
    {"code": "orange", "name": "Orange Madagascar"},
    {"code": "yas", "name": "Yas Madagascar"},
    {"code": "airtel", "name": "Airtel Madagascar"},
]


def seed_operators(operator_model):
    for data in INITIAL_OPERATORS:
        # update_or_create sur `code` : ré-exécutable sans doublon.
        operator_model.objects.update_or_create(code=data["code"], defaults={"name": data["name"]})
