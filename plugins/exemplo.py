"""Plugin de exemplo. Para ativar: em config.yaml  plugins.enabled: ["exemplo"]
Cada ação precisa de: nome, descrição, schema JSON dos argumentos e nível de risco (0-3)."""
from eddy.actions.registry import ActionResult, action, obj


@action("dado_aleatorio", "Lança um dado de N faces (padrão 6).",
        obj({"faces": {"type": "integer", "minimum": 2, "maximum": 1000}}), risk=0, family="extras")
def dado_aleatorio(ctx, faces: int = 6) -> ActionResult:
    import random
    return ActionResult(True, f"Saiu {random.randint(1, faces)}.")
