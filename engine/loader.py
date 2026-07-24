"""
loader.py
Loads and validates data files.
Does not perform any simulation.
"""

import json
from pathlib import Path


def load_json(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(
            f"Data file not found: {filepath}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ingredients(filepath: str) -> dict:
    data = load_json(filepath)
    return data["ingredients"]


def load_recipes(filepath: str) -> dict:
    data = load_json(filepath)
    return data["recipes"]


def load_model_parameters(filepath: str) -> dict:
    data = load_json(filepath)
    return data["parameters"]


def resolve_recipe(
    recipe_id: str,
    recipes: dict,
    ingredients: dict,
) -> dict:
    """
    Returns the recipe dict after confirming every
    ingredient reference exists in the ingredient database.

    Raises
    ------
    KeyError
        If recipe_id is not found.
        If any ingredient reference cannot be resolved.
    """
    if recipe_id not in recipes:
        raise KeyError(f"Recipe not found: {recipe_id}")

    recipe = recipes[recipe_id]

    for ing_id in recipe["ingredients"]:
        if ing_id not in ingredients:
            raise KeyError(
                f"Recipe '{recipe_id}' references ingredient "
                f"'{ing_id}' which is not in ingredients.json"
            )

    return recipe