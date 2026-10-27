from .constants import DEFAULT_SURVEY, INITIAL_CRITERIA


def seed_criteria(criterion_model, survey_model, link_model):
    criteria = []
    for pos, (code, cat, label, desc) in enumerate(INITIAL_CRITERIA, start=1):
        obj, _ = criterion_model.objects.update_or_create(
            code=code, defaults={"category": cat, "label": label, "description": desc, "position": pos}
        )
        criteria.append(obj)
    survey, created = survey_model.objects.get_or_create(slug=DEFAULT_SURVEY["slug"], defaults=DEFAULT_SURVEY)
    if created:  # ne jamais réécrire un sondage que l'ARTEC a pu modifier
        for pos, crit in enumerate(criteria, start=1):
            link_model.objects.get_or_create(survey_form=survey, criterion=crit, defaults={"position": pos})
