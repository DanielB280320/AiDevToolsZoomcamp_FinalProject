"""F6 food library and meal seed: ~60 foods and 50+ meals, loaded by the migration step (D50).

Idempotent, same rules as `seed_exercises`: an entry is inserted only when neither its
deterministic id (uuid5 of the lower-cased name, per kind) nor its lower-cased name among seed
rows exists. A seed row renamed or edited later is never overwritten or duplicated into a unique
violation, custom rows are never touched, and nothing is updated or deleted. A meal's items are
written together with the meal, never to an existing one.

Macros are per 100 g (USDA FoodData Central values, rounded; cooked weights for rice, pasta,
pulses, meat and fish). Diet tags list every diet the food suits besides omnivore: a vegan food
carries `vegan`, `vegetarian` and `pescatarian`; a vegetarian one `vegetarian` and `pescatarian`;
fish and shellfish only `pescatarian`; meat and poultry none (F6.5). A meal's diets and
allergens are derived from its foods (`app.engines.meal_macros`), never stored.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Food, Meal, MealItem

_FOOD_NAMESPACE = uuid.UUID("0b8d3c52-6f1a-4e57-a7c4-2d9e5b1f8a63")
_MEAL_NAMESPACE = uuid.UUID("c4a1e9f7-83d2-4b06-95ab-7e30d1c6f248")

VGN = ("vegan", "vegetarian", "pescatarian")
VEG = ("vegetarian", "pescatarian")
PESC = ("pescatarian",)
OMNI: tuple[str, ...] = ()


class SeedFood(NamedTuple):
    name: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    diet_tags: tuple[str, ...]
    allergen_tags: tuple[str, ...] = ()


SEED_FOODS: tuple[SeedFood, ...] = (
    # plant foods
    SeedFood("Rolled oats", 379, 13.2, 67.7, 6.5, VGN, ("gluten",)),
    SeedFood("Banana", 89, 1.1, 22.8, 0.3, VGN),
    SeedFood("Apple", 52, 0.3, 13.8, 0.2, VGN),
    SeedFood("Blueberries", 57, 0.7, 14.5, 0.3, VGN),
    SeedFood("Strawberries", 32, 0.7, 7.7, 0.3, VGN),
    SeedFood("Dates", 282, 2.5, 75.0, 0.4, VGN),
    SeedFood("Peanut butter", 588, 25.0, 20.0, 50.0, VGN, ("nuts",)),
    SeedFood("Almonds", 579, 21.2, 21.6, 49.9, VGN, ("nuts",)),
    SeedFood("Walnuts", 654, 15.2, 13.7, 65.2, VGN, ("nuts",)),
    SeedFood("Chia seeds", 486, 16.5, 42.1, 30.7, VGN),
    SeedFood("Soy milk, unsweetened", 33, 2.9, 1.7, 1.6, VGN, ("soy",)),
    SeedFood("Whole wheat bread", 247, 13.0, 41.0, 3.4, VGN, ("gluten",)),
    SeedFood("Whole wheat tortilla", 310, 8.5, 50.0, 8.0, VGN, ("gluten",)),
    SeedFood("Whole wheat pasta, cooked", 124, 5.3, 25.0, 0.5, VGN, ("gluten",)),
    SeedFood("Brown rice, cooked", 123, 2.7, 25.6, 1.0, VGN),
    SeedFood("White rice, cooked", 130, 2.7, 28.2, 0.3, VGN),
    SeedFood("Rice cakes", 387, 8.0, 81.0, 2.8, VGN),
    SeedFood("Quinoa, cooked", 120, 4.4, 21.3, 1.9, VGN),
    SeedFood("Potato, boiled", 87, 1.9, 20.1, 0.1, VGN),
    SeedFood("Sweet potato, baked", 90, 2.0, 20.7, 0.2, VGN),
    SeedFood("Lentils, cooked", 116, 9.0, 20.1, 0.4, VGN),
    SeedFood("Chickpeas, cooked", 164, 8.9, 27.4, 2.6, VGN),
    SeedFood("Black beans, cooked", 132, 8.9, 23.7, 0.5, VGN),
    SeedFood("Tofu, firm", 144, 17.3, 2.8, 8.7, VGN, ("soy",)),
    SeedFood("Tempeh", 192, 20.3, 7.6, 10.8, VGN, ("soy",)),
    SeedFood("Pea protein powder", 380, 78.0, 8.0, 6.0, VGN),
    SeedFood("Hummus", 177, 4.9, 14.3, 11.6, VGN),
    SeedFood("Avocado", 160, 2.0, 8.5, 14.7, VGN),
    SeedFood("Olive oil", 884, 0.0, 0.0, 100.0, VGN),
    SeedFood("Broccoli", 34, 2.8, 6.6, 0.4, VGN),
    SeedFood("Spinach", 23, 2.9, 3.6, 0.4, VGN),
    SeedFood("Tomato", 18, 0.9, 3.9, 0.2, VGN),
    SeedFood("Cucumber", 15, 0.7, 3.6, 0.1, VGN),
    SeedFood("Carrot", 41, 0.9, 9.6, 0.2, VGN),
    SeedFood("Bell pepper", 31, 1.0, 6.0, 0.3, VGN),
    SeedFood("Mixed salad greens", 17, 1.4, 3.3, 0.2, VGN),
    # eggs and dairy
    SeedFood("Egg, whole", 143, 12.6, 0.7, 9.5, VEG, ("eggs",)),
    SeedFood("Greek yogurt, nonfat", 59, 10.2, 3.6, 0.4, VEG, ("lactose",)),
    SeedFood("Milk, semi-skimmed", 46, 3.4, 4.8, 1.6, VEG, ("lactose",)),
    SeedFood("Cheddar cheese", 403, 24.9, 1.3, 33.1, VEG, ("lactose",)),
    SeedFood("Feta cheese", 264, 14.2, 4.1, 21.3, VEG, ("lactose",)),
    SeedFood("Cottage cheese", 98, 11.1, 3.4, 4.3, VEG, ("lactose",)),
    SeedFood("Mozzarella", 280, 28.0, 3.1, 17.1, VEG, ("lactose",)),
    SeedFood("Whey protein powder", 400, 80.0, 8.0, 6.0, VEG, ("lactose",)),
    SeedFood("Honey", 304, 0.3, 82.4, 0.0, VEG),
    # fish and shellfish
    SeedFood("Salmon, cooked", 206, 22.1, 0.0, 12.4, PESC, ("fish",)),
    SeedFood("Tuna, canned in water", 116, 25.5, 0.0, 0.8, PESC, ("fish",)),
    SeedFood("Cod, cooked", 105, 22.8, 0.0, 0.9, PESC, ("fish",)),
    SeedFood("Shrimp, cooked", 99, 24.0, 0.2, 0.3, PESC, ("shellfish",)),
    # meat and poultry
    SeedFood("Chicken breast, cooked", 165, 31.0, 0.0, 3.6, OMNI),
    SeedFood("Turkey breast, cooked", 135, 30.0, 0.0, 1.0, OMNI),
    SeedFood("Beef mince 10% fat, cooked", 217, 26.1, 0.0, 11.7, OMNI),
    SeedFood("Beef sirloin steak, cooked", 206, 27.0, 0.0, 10.0, OMNI),
    SeedFood("Lean ham", 145, 21.0, 1.5, 5.5, OMNI),
)


class SeedMeal(NamedTuple):
    name: str
    slots: tuple[str, ...]
    items: tuple[tuple[str, float], ...]


BF, LU, DI, SN = "breakfast", "lunch", "dinner", "snack"

SEED_MEALS: tuple[SeedMeal, ...] = (
    # breakfast
    SeedMeal(
        "Oatmeal with banana and peanut butter",
        (BF,),
        (
            ("Rolled oats", 60),
            ("Soy milk, unsweetened", 250),
            ("Banana", 100),
            ("Peanut butter", 15),
        ),
    ),
    SeedMeal(
        "Chia pudding with blueberries",
        (BF, SN),
        (("Chia seeds", 30), ("Soy milk, unsweetened", 200), ("Blueberries", 80), ("Dates", 15)),
    ),
    SeedMeal(
        "Tofu scramble with spinach and toast",
        (BF,),
        (
            ("Tofu, firm", 150),
            ("Spinach", 50),
            ("Whole wheat bread", 60),
            ("Olive oil", 5),
            ("Tomato", 80),
        ),
    ),
    SeedMeal(
        "Overnight oats with strawberries",
        (BF,),
        (
            ("Rolled oats", 50),
            ("Soy milk, unsweetened", 200),
            ("Strawberries", 100),
            ("Chia seeds", 10),
        ),
    ),
    SeedMeal(
        "Peanut butter banana toast",
        (BF, SN),
        (("Whole wheat bread", 80), ("Peanut butter", 20), ("Banana", 100)),
    ),
    SeedMeal(
        "Avocado toast with tomato",
        (BF,),
        (("Whole wheat bread", 80), ("Avocado", 70), ("Tomato", 80)),
    ),
    SeedMeal(
        "Smoothie bowl with oats and berries",
        (BF, SN),
        (
            ("Banana", 120),
            ("Blueberries", 80),
            ("Soy milk, unsweetened", 150),
            ("Rolled oats", 30),
            ("Chia seeds", 10),
        ),
    ),
    SeedMeal(
        "Scrambled eggs on toast",
        (BF,),
        (("Egg, whole", 150), ("Whole wheat bread", 60), ("Olive oil", 5), ("Tomato", 80)),
    ),
    SeedMeal(
        "Greek yogurt with oats and blueberries",
        (BF,),
        (("Greek yogurt, nonfat", 200), ("Rolled oats", 40), ("Blueberries", 80), ("Honey", 10)),
    ),
    SeedMeal(
        "Cottage cheese with strawberries",
        (BF, SN),
        (("Cottage cheese", 200), ("Strawberries", 100), ("Almonds", 15)),
    ),
    SeedMeal(
        "Spinach and feta omelette",
        (BF,),
        (
            ("Egg, whole", 150),
            ("Spinach", 50),
            ("Bell pepper", 50),
            ("Feta cheese", 30),
            ("Olive oil", 5),
        ),
    ),
    SeedMeal(
        "Protein oats with banana",
        (BF,),
        (
            ("Rolled oats", 60),
            ("Milk, semi-skimmed", 250),
            ("Whey protein powder", 25),
            ("Banana", 100),
        ),
    ),
    SeedMeal(
        "Egg and avocado toast",
        (BF,),
        (("Egg, whole", 100), ("Whole wheat bread", 70), ("Avocado", 60)),
    ),
    SeedMeal(
        "Salmon and egg breakfast bowl",
        (BF,),
        (("Salmon, cooked", 100), ("Egg, whole", 100), ("Whole wheat bread", 60), ("Avocado", 50)),
    ),
    SeedMeal(
        "Turkey and egg breakfast wrap",
        (BF,),
        (
            ("Whole wheat tortilla", 70),
            ("Egg, whole", 100),
            ("Turkey breast, cooked", 60),
            ("Tomato", 50),
        ),
    ),
    SeedMeal(
        "Ham and cheese sandwich",
        (BF, LU),
        (("Whole wheat bread", 80), ("Lean ham", 50), ("Cheddar cheese", 30), ("Tomato", 50)),
    ),
    # lunch
    SeedMeal(
        "Chickpea quinoa bowl",
        (LU,),
        (
            ("Quinoa, cooked", 150),
            ("Chickpeas, cooked", 120),
            ("Cucumber", 80),
            ("Tomato", 80),
            ("Olive oil", 10),
        ),
    ),
    SeedMeal(
        "Lentil and sweet potato bowl",
        (LU, DI),
        (
            ("Lentils, cooked", 150),
            ("Sweet potato, baked", 150),
            ("Spinach", 50),
            ("Brown rice, cooked", 120),
        ),
    ),
    SeedMeal(
        "Black bean burrito bowl",
        (LU,),
        (
            ("Black beans, cooked", 150),
            ("White rice, cooked", 150),
            ("Avocado", 60),
            ("Bell pepper", 60),
            ("Tomato", 60),
        ),
    ),
    SeedMeal(
        "Hummus veggie wrap",
        (LU, SN),
        (
            ("Whole wheat tortilla", 80),
            ("Hummus", 60),
            ("Carrot", 50),
            ("Cucumber", 50),
            ("Mixed salad greens", 40),
        ),
    ),
    SeedMeal(
        "Tofu stir-fry with rice",
        (LU, DI),
        (
            ("Tofu, firm", 150),
            ("Broccoli", 120),
            ("Brown rice, cooked", 150),
            ("Carrot", 50),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Quinoa veggie salad",
        (LU, DI),
        (
            ("Quinoa, cooked", 150),
            ("Chickpeas, cooked", 100),
            ("Bell pepper", 60),
            ("Cucumber", 80),
            ("Mixed salad greens", 40),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Caprese pasta salad",
        (LU,),
        (("Whole wheat pasta, cooked", 180), ("Mozzarella", 60), ("Tomato", 100), ("Olive oil", 8)),
    ),
    SeedMeal(
        "Greek salad with chickpeas",
        (LU,),
        (
            ("Mixed salad greens", 100),
            ("Cucumber", 100),
            ("Tomato", 100),
            ("Feta cheese", 50),
            ("Olive oil", 10),
            ("Chickpeas, cooked", 100),
        ),
    ),
    SeedMeal(
        "Egg fried rice",
        (LU, DI),
        (
            ("Brown rice, cooked", 180),
            ("Egg, whole", 100),
            ("Broccoli", 60),
            ("Carrot", 50),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Tuna salad bowl",
        (LU,),
        (
            ("Tuna, canned in water", 120),
            ("Quinoa, cooked", 120),
            ("Mixed salad greens", 60),
            ("Cucumber", 60),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Salmon rice bowl",
        (LU, DI),
        (("Salmon, cooked", 120), ("White rice, cooked", 150), ("Broccoli", 80), ("Avocado", 40)),
    ),
    SeedMeal(
        "Shrimp tomato pasta",
        (LU, DI),
        (
            ("Shrimp, cooked", 120),
            ("Whole wheat pasta, cooked", 180),
            ("Tomato", 100),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Chicken, rice and broccoli",
        (LU, DI),
        (
            ("Chicken breast, cooked", 150),
            ("White rice, cooked", 180),
            ("Broccoli", 100),
            ("Olive oil", 5),
        ),
    ),
    SeedMeal(
        "Turkey quinoa bowl",
        (LU,),
        (
            ("Turkey breast, cooked", 140),
            ("Quinoa, cooked", 150),
            ("Spinach", 50),
            ("Bell pepper", 60),
        ),
    ),
    SeedMeal(
        "Beef burrito bowl",
        (LU, DI),
        (
            ("Beef mince 10% fat, cooked", 120),
            ("White rice, cooked", 150),
            ("Black beans, cooked", 80),
            ("Tomato", 60),
        ),
    ),
    SeedMeal(
        "Chicken hummus wrap",
        (LU,),
        (
            ("Whole wheat tortilla", 80),
            ("Chicken breast, cooked", 120),
            ("Mixed salad greens", 40),
            ("Tomato", 50),
            ("Hummus", 30),
        ),
    ),
    # dinner
    SeedMeal(
        "Tempeh stir-fry with rice",
        (DI,),
        (
            ("Tempeh", 130),
            ("Brown rice, cooked", 150),
            ("Broccoli", 100),
            ("Bell pepper", 60),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Chickpea tomato stew with potatoes",
        (DI,),
        (("Chickpeas, cooked", 180), ("Potato, boiled", 200), ("Tomato", 100), ("Spinach", 50)),
    ),
    SeedMeal(
        "Lentil bolognese pasta",
        (DI,),
        (
            ("Lentils, cooked", 130),
            ("Whole wheat pasta, cooked", 200),
            ("Tomato", 120),
            ("Carrot", 40),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Tofu veggie curry with rice",
        (DI,),
        (("Tofu, firm", 150), ("White rice, cooked", 150), ("Spinach", 60), ("Tomato", 80)),
    ),
    SeedMeal(
        "Spinach and feta frittata with potatoes",
        (DI,),
        (("Egg, whole", 200), ("Spinach", 80), ("Feta cheese", 40), ("Potato, boiled", 200)),
    ),
    SeedMeal(
        "Mozzarella veggie quesadilla",
        (DI,),
        (
            ("Whole wheat tortilla", 100),
            ("Mozzarella", 60),
            ("Bell pepper", 60),
            ("Spinach", 40),
            ("Black beans, cooked", 80),
        ),
    ),
    SeedMeal(
        "Baked salmon with sweet potato",
        (DI,),
        (
            ("Salmon, cooked", 150),
            ("Sweet potato, baked", 200),
            ("Broccoli", 120),
            ("Olive oil", 5),
        ),
    ),
    SeedMeal(
        "Cod with quinoa and broccoli",
        (DI,),
        (("Cod, cooked", 180), ("Quinoa, cooked", 150), ("Broccoli", 100), ("Olive oil", 8)),
    ),
    SeedMeal(
        "Garlic shrimp with rice",
        (DI,),
        (
            ("Shrimp, cooked", 150),
            ("White rice, cooked", 150),
            ("Bell pepper", 80),
            ("Broccoli", 80),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Grilled chicken with potatoes and salad",
        (DI,),
        (
            ("Chicken breast, cooked", 170),
            ("Potato, boiled", 250),
            ("Mixed salad greens", 60),
            ("Tomato", 60),
            ("Olive oil", 8),
        ),
    ),
    SeedMeal(
        "Beef steak with rice and broccoli",
        (DI,),
        (("Beef sirloin steak, cooked", 150), ("White rice, cooked", 150), ("Broccoli", 100)),
    ),
    SeedMeal(
        "Turkey meatball pasta",
        (DI,),
        (("Turkey breast, cooked", 150), ("Whole wheat pasta, cooked", 200), ("Tomato", 120)),
    ),
    # snacks
    SeedMeal("Apple with peanut butter", (SN,), (("Apple", 180), ("Peanut butter", 20))),
    SeedMeal("Banana and almonds", (SN,), (("Banana", 120), ("Almonds", 25))),
    SeedMeal(
        "Hummus with carrot and cucumber sticks",
        (SN,),
        (("Hummus", 60), ("Carrot", 120), ("Cucumber", 60)),
    ),
    SeedMeal("Nut and date trail mix", (SN,), (("Almonds", 20), ("Walnuts", 15), ("Dates", 25))),
    SeedMeal("Rice cakes with avocado", (SN,), (("Rice cakes", 30), ("Avocado", 60))),
    SeedMeal(
        "Pea protein shake with banana",
        (SN,),
        (("Pea protein powder", 30), ("Soy milk, unsweetened", 250), ("Banana", 100)),
    ),
    SeedMeal(
        "Greek yogurt with honey and walnuts",
        (SN,),
        (("Greek yogurt, nonfat", 200), ("Honey", 12), ("Walnuts", 10)),
    ),
    SeedMeal(
        "Cottage cheese with tomato and rice cakes",
        (SN,),
        (("Cottage cheese", 150), ("Tomato", 100), ("Rice cakes", 20)),
    ),
    SeedMeal(
        "Whey shake with milk and banana",
        (SN,),
        (("Whey protein powder", 30), ("Milk, semi-skimmed", 250), ("Banana", 100)),
    ),
    SeedMeal(
        "Tuna on rice cakes",
        (SN,),
        (("Tuna, canned in water", 80), ("Rice cakes", 30), ("Cucumber", 50)),
    ),
    SeedMeal(
        "Turkey and cheese roll-up",
        (SN,),
        (("Turkey breast, cooked", 60), ("Cheddar cheese", 25), ("Whole wheat tortilla", 40)),
    ),
    SeedMeal(
        "Chicken and cucumber with hummus",
        (SN,),
        (("Chicken breast, cooked", 100), ("Cucumber", 80), ("Hummus", 30)),
    ),
)


def food_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_FOOD_NAMESPACE, name.lower())


def meal_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_MEAL_NAMESPACE, name.lower())


def load_foods(session: Session) -> int:
    """Insert the seed foods that are missing. Returns how many rows were inserted."""
    names = set(session.scalars(select(func.lower(Food.name)).where(Food.source == "seed")))
    ids = {food_id(item.name) for item in SEED_FOODS}
    ids = set(session.scalars(select(Food.id).where(Food.id.in_(ids))))
    inserted = 0
    for item in SEED_FOODS:
        if item.name.lower() in names or food_id(item.name) in ids:
            continue
        session.add(
            Food(
                id=food_id(item.name),
                owner_id=None,
                source="seed",
                name=item.name,
                kcal_per_100g=item.kcal,
                protein_g_per_100g=item.protein_g,
                carbs_g_per_100g=item.carbs_g,
                fat_g_per_100g=item.fat_g,
                diet_tags=list(item.diet_tags),
                allergen_tags=list(item.allergen_tags),
            )
        )
        inserted += 1
    session.flush()
    return inserted


def load_meals(session: Session) -> int:
    """Insert the seed meals (with their items) that are missing. Returns the rows inserted
    (meals plus items). Runs after `load_foods`."""
    food_ids: dict[str, uuid.UUID] = {}
    for name, id_ in session.execute(
        select(func.lower(Food.name), Food.id).where(Food.source == "seed")
    ):
        food_ids[name] = id_
    names = set(session.scalars(select(func.lower(Meal.name)).where(Meal.source == "seed")))
    existing = set(
        session.scalars(select(Meal.id).where(Meal.id.in_([meal_id(m.name) for m in SEED_MEALS])))
    )
    inserted = 0
    for meal in SEED_MEALS:
        if meal.name.lower() in names or meal_id(meal.name) in existing:
            continue
        session.add(
            Meal(
                id=meal_id(meal.name),
                owner_id=None,
                source="seed",
                name=meal.name,
                slots=list(meal.slots),
            )
        )
        session.flush()
        for position, (food_name, grams) in enumerate(meal.items):
            session.add(
                MealItem(
                    meal_id=meal_id(meal.name),
                    food_id=food_ids.get(food_name.lower(), food_id(food_name)),
                    position=position,
                    grams=grams,
                )
            )
            inserted += 1
        inserted += 1
    session.flush()
    return inserted
