from eddy.briefing import Briefing


def run(ctx, user_input=""):
    b = ctx.extras.get("briefing") or Briefing(ctx.cfg)
    if b._weather is None:
        b.fetch_weather()            # aqui pode esperar um pouco: é pedido explícito
    data = b.build(ctx.extras["eddy"], with_weather=False) if ctx.extras.get("eddy") else {}
    if not data:
        return "SEM DADOS."
    data["weather"] = b._weather
    if data["news"] and ctx.session is not None:
        ctx.session.tainted = True
    return Briefing.as_text(data)
