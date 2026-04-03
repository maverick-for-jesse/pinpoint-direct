"""
Permit type classifier for Pinpoint Direct.
Classifies raw permit description text into standardized categories.
"""

# Rules: list of (category, [keywords/phrases]) — checked in order, first match wins
PERMIT_RULES = [
    ('Pool', [
        'pool', 'swimming pool', 'inground pool', 'in-ground pool', 'in ground pool',
        'pool/spa', 'spa', 'hot tub', 'swim spa',
    ]),
    ('Detached Garage', [
        'detached garage',
    ]),
    ('Deck/Patio', [
        'deck', 'patio', 'pergola', 'gazebo', 'screen porch', 'screened porch',
        'covered porch', 'sunroom', 'lanai',
    ]),
    ('Home Addition', [
        'addition', 'room addition', 'master suite addition', 'bump out',
        'home addition', 'residential addition', 'house addition',
    ]),
    ('Roof', [
        'roof', 'roofing', 'reroof', 're-roof', 'shingle', 'metal roof',
    ]),
    ('HVAC', [
        'hvac', 'heating', 'cooling', 'air conditioning', 'heat pump', 'furnace',
        'mechanical', 'ductwork',
    ]),
    ('New Construction', [
        'new construction', 'new single family', 'new sfr', 'new home', 'new residence',
        'new dwelling', 'new house', 'single family new',
    ]),
    ('Fence', [
        'fence', 'fencing',
    ]),
    ('Driveway/Concrete', [
        'driveway', 'concrete', 'flatwork', 'sidewalk', 'apron',
    ]),
    ('Electrical', [
        'electrical', 'electric', 'panel upgrade', 'service upgrade', 'generator',
        'ev charger', 'solar',
    ]),
    ('Plumbing', [
        'plumbing', 'water heater', 'sewer', 'septic',
    ]),
]


def classify_permit(description: str) -> str:
    """
    Classify a permit description string into a standard category.
    Returns category name string, or 'Other' if no match.
    """
    if not description:
        return 'Other'
    desc_lower = description.lower()
    for category, keywords in PERMIT_RULES:
        for kw in keywords:
            if kw in desc_lower:
                return category
    return 'Other'


def classify_batch(descriptions: list) -> list:
    """Classify a list of descriptions. Returns list of category strings."""
    return [classify_permit(d) for d in descriptions]


def get_category_summary(descriptions: list) -> dict:
    """
    Returns a dict of {category: count} for a batch of descriptions.
    Useful for showing upload preview.
    """
    counts = {}
    for d in descriptions:
        cat = classify_permit(d)
        counts[cat] = counts.get(cat, 0) + 1
    return dict(sorted(counts.items()))
